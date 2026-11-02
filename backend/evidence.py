"""Source acquisition and display links; never changes Retrieve or Student inputs."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs

MAX_BYTES = 512 * 1024
FETCH_TIMEOUT = 7
MAX_FETCHES = 5


def public_address(value):
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not address.is_reserved


def public_url(url):
    """Syntactic filter; DNS and every redirect are checked again before connecting."""
    try:
        p = urlsplit(url)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username
                or p.password or p.port not in (None, 80, 443)
                or any(ord(c) < 33 for c in url) or '\\' in url):
            return None
        host = p.hostname.lower().rstrip('.')
        if '.' not in host or host.endswith(('.localhost', '.local', '.internal')):
            return None
        try:
            if not public_address(host):
                return None
        except ValueError:
            pass
        return url
    except (ValueError, TypeError):
        return None


class PageText(HTMLParser):
    """Keep the normalized page text and separately identify publisher article text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.article_parts, self.main_parts, self.title_parts = [], [], [], []
        self.stack = []
        self.link_parts = []
        self.meta = {}
        self.date = None
        self.date_provenance = None
        self.canonical = None
        self.jsonld = []
        self.script_text = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and 'canonical' in attrs.get('rel', '').lower().split():
            self.canonical = attrs.get('href')
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.script_text = []
        if tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            self.meta.setdefault(key, attrs.get('content', '').strip())
            if key in ('article:published_time', 'datepublished', 'pubdate', 'dc.date.issued'):
                self.set_date(attrs.get('content', ''), key)
        if tag == 'time' and attrs.get('itemprop') == 'datePublished':
            self.set_date(attrs.get('datetime', ''), 'time[itemprop=datePublished]')
        if tag not in ('meta', 'link', 'img', 'br', 'hr', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track'):
            self.stack.append(tag)

    def set_date(self, value, provenance):
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            if not self.date:
                self.date, self.date_provenance = value, provenance
        except ValueError:
            pass

    def handle_endtag(self, tag):
        if tag == 'script' and self.script_text is not None:
            try:
                self.jsonld.append(json.loads(''.join(self.script_text)))
            except (ValueError, TypeError):
                pass
            self.script_text = None
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]

    def handle_data(self, data):
        if self.script_text is not None:
            self.script_text.append(data)
        if any(tag in self.stack for tag in ('script', 'style', 'noscript', 'template', 'svg')) or not data.strip():
            return
        value = data.strip()
        self.parts.append(value)
        if 'a' in self.stack:
            self.link_parts.append(value)
        if 'title' in self.stack:
            self.title_parts.append(value)
        if not any(tag in self.stack for tag in ('nav', 'footer', 'header', 'aside')):
            if 'article' in self.stack:
                self.article_parts.append(value)
            elif 'main' in self.stack:
                self.main_parts.append(value)


def youtube_info(url):
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        if not (host == 'youtu.be' or host == 'youtube.com' or host.endswith('.youtube.com')):
            return None
        candidate = p.path.strip('/').split('/')[0] if host == 'youtu.be' else parse_qs(p.query).get('v', [None])[0]
        if not candidate and p.path.startswith(('/shorts/', '/embed/')):
            candidate = p.path.split('/')[2]
        return {'source_kind': 'youtube', 'video_id': candidate if candidate and re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else None}
    except (ValueError, IndexError):
        return None



def article_quality(candidate, parser, node):
    """Conservative article gate; length alone never establishes article identity."""
    if not isinstance(candidate, str) or not candidate.strip():
        return None, 'empty_result'
    candidate = candidate.strip()
    norm = lambda value: ' '.join(value.split())
    letters = sum(c.isalpha() for c in candidate)
    if len(candidate) < 80 or letters < 40 or not re.search(r'[.!?。！？]', candidate):
        return None, 'too_short_or_not_prose'
    context = bool(parser.article_parts or node or parser.meta.get('og:type') == 'article')
    if not context:
        return None, 'article_identity_unconfirmed'
    visible = norm(' '.join(parser.parts))
    declared = norm(node.get('articleBody', '')) if isinstance(node.get('articleBody'), str) else ''
    lines = [norm(line) for line in candidate.splitlines() if line.strip()]
    if any(line not in visible and line not in declared for line in lines):
        return None, 'text_not_verifiable_in_html'
    links = sum(len(part) for part in parser.link_parts if norm(part) in norm(candidate))
    noise = re.compile(r'^(subscribe|sign in|log in|advertisement|related (articles|stories)|recommended|privacy policy|cookie settings|menu|home|訂閱|登入|廣告|推薦閱讀)\b', re.I)
    if re.search(r'subscribe to (continue|read)|sign in to (continue|read)|enable javascript and cookies|verify you are human', candidate, re.I):
        return None, 'access_wall_or_challenge_text'
    if links > len(candidate) * .35 or sum(len(line) for line in lines if noise.search(line)) > len(candidate) * .2:
        return None, 'navigation_or_promotional_text'
    # Full means the complete publisher-declared body is represented, not that a
    # paywall/website has been independently proved to expose the entire story.
    full = bool(node.get('isAccessibleForFree') not in (False, 'false') and declared and norm(candidate) == declared and len(candidate) >= 200
                and len(re.findall(r'[.!?。！？]', candidate)) >= 2)
    return 'full_article' if full else 'partial_article', None


def extract_article(html, parser, node, url):
    path = urlsplit(url).path.lower()
    host = (urlsplit(url).hostname or '').lower()
    title = ' '.join(parser.title_parts).lower()
    excluded = (youtube_info(url) or host in ('google.com', 'www.google.com', 'consent.google.com', 'vertexaisearch.cloud.google.com')
                or path in ('', '/') or re.search(r'/(search|search-results)(/|$)', path)
                or re.search(r'search results|access denied|just a moment|client challenge|captcha|verify you are human|搜尋結果|存取遭拒', title))
    meta = {'quality_rule': 'article-quality-v1', 'attempts': [],
            'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest()}
    if excluded:
        return None, None, 'page_text_only', {**meta, 'reason': 'non_article_or_challenge_page'}
    try:
        import trafilatura
        candidate = trafilatura.extract(html, output_format='txt', include_comments=False,
                                         include_tables=False, favor_precision=True)
        quality, error = article_quality(candidate, parser, node)
        meta['attempts'].append({'method': 'trafilatura', 'version': trafilatura.__version__, 'error': error})
        if quality:
            return candidate.strip(), 'trafilatura:extract', quality, meta
    except Exception as error:
        meta['attempts'].append({'method': 'trafilatura', 'error': type(error).__name__})
    candidates = [('html:article', '\n'.join(parser.article_parts)),
                  ('html:main', '\n'.join(parser.main_parts)),
                  ('jsonld:articleBody', node.get('articleBody'))]
    for method, candidate in candidates:
        if not candidate:
            continue
        quality, error = article_quality(candidate, parser, node)
        meta['attempts'].append({'method': method, 'error': error})
        if quality:
            return candidate.strip(), method, quality, meta
    article_context = bool(parser.article_parts or node or parser.meta.get('og:type') == 'article')
    quality = 'extraction_failed' if not parser.parts or (article_context and any(value for _, value in candidates)) else 'page_text_only'
    return None, None, quality, meta


def acquisition_quality(result):
    """Additive classification; old status enums and saved versions stay intact."""
    if result.get('retrieval_status') in ('not_fetched', 'budget_exceeded'):
        return 'not_attempted'
    if result.get('retrieval_status') in ('fetched', 'content_unavailable'):
        return 'partial_article' if result.get('article_text') else 'page_text_only'
    if result.get('retrieval_status') == 'unextractable':
        return 'extraction_failed'
    return 'fetch_failed'

def parse_page(body, url, charset='utf-8'):
    parser = PageText()
    html = body.decode(charset, errors='replace')
    parser.feed(html)
    text = '\n'.join(parser.parts)
    title = parser.meta.get('og:title') or parser.meta.get('twitter:title') or ' '.join(parser.title_parts) or None
    def article_nodes(value):
        if isinstance(value, list):
            for item in value:
                yield from article_nodes(item)
        elif isinstance(value, dict):
            kinds = value.get('@type', [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if any(k in ('NewsArticle', 'Article', 'ReportageNewsArticle', 'BlogPosting') for k in kinds):
                yield value
            yield from article_nodes(value.get('@graph', []))
    node = next(article_nodes(parser.jsonld), {})
    article, method, quality, extraction = extract_article(html, parser, node, url)
    if not title and isinstance(node.get('headline'), str):
        title = node['headline']
    if isinstance(node.get('datePublished'), str):
        parser.set_date(node['datePublished'], 'jsonld:datePublished')
    result = {'retrieval_status': 'fetched' if text or article else 'unextractable',
              'resolved_url': url, 'source_text': text, 'article_text': article or None,
              'article_text_provenance': method,
              'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
              'article_text_sha256': hashlib.sha256(article.encode('utf-8')).hexdigest() if article else None,
              'article_title': title, 'title_provenance': 'og:title' if parser.meta.get('og:title') else 'twitter:title' if parser.meta.get('twitter:title') else 'html:title' if parser.title_parts else 'jsonld:headline' if title else None,
              'publisher_name': parser.meta.get('og:site_name') or None,
              'publisher_provenance': 'og:site_name' if parser.meta.get('og:site_name') else None,
              'published_date': parser.date, 'date_provenance': parser.date_provenance,
              'content_sha256': hashlib.sha256(body).hexdigest(),
              'fetched_at': datetime.now(timezone.utc).isoformat(), 'source_kind': 'article',
              'extraction_status': 'article_text' if article else 'page_text_only' if text else 'no_text'}
    result.update(content_quality=quality, extraction_method=method, extraction_metadata=extraction)
    extraction['completeness_basis'] = 'complete_publisher_declared_articleBody_match' if quality == 'full_article' else 'completeness_not_established'
    if not article:
        result['extraction_error'] = extraction.get('reason') or 'no_candidate_passed_article_quality'
    parsed_url = urlsplit(url)
    canonical = public_url(urljoin(url, parser.canonical)) if parser.canonical else None
    result['canonical_url'] = canonical
    result['canonical_provenance'] = 'html:link[rel=canonical]; publisher-declared, not fetched' if canonical else None
    result['source_type'] = 'news_article' if article and (node or parser.meta.get('og:type') == 'article' or parser.date) else 'webpage'
    # Search, challenge and home pages are not article evidence, even with <main>.
    google_page = parsed_url.hostname in ('google.com', 'www.google.com', 'consent.google.com')
    intermediary = parsed_url.hostname == 'vertexaisearch.cloud.google.com'
    if google_page or intermediary or parsed_url.path in ('', '/'):
        result.update(article_text=None, article_text_sha256=None, article_text_provenance=None,
                      source_type='search_page' if google_page else 'webpage', extraction_status='non_article_page',
                      extraction_error='search_challenge_redirect_or_home_page')
    if parsed_url.hostname == 'vertexaisearch.cloud.google.com' and parsed_url.path.startswith('/grounding-api-redirect'):
        result.update(retrieval_status='redirect_unresolved', retrieval_error='grounding_redirect_did_not_resolve', extraction_status='redirect_page_only')
    youtube = youtube_info(url)
    if youtube:
        # HTML/title is metadata, never evidence of spoken video content.
        result.update(youtube, article_text=None, article_text_sha256=None,
                      article_text_provenance=None, retrieval_status='content_unavailable',
                      extraction_status='youtube_metadata_only', transcript_status='not_obtained')
        result['source_type'] = 'youtube'
    # Canonical only groups same-host article identities; it is never fetched automatically.
    identity = canonical if canonical and urlsplit(canonical).hostname == parsed_url.hostname else url
    identity = identity.split('#', 1)[0]
    result.update(article_id=hashlib.sha256(identity.encode()).hexdigest(), title=result['article_title'],
                  published_at=result['published_date'], article_text_hash=result['article_text_sha256'])
    return result


def attach_public_transcript(source, text, transcript_url, language=None):
    """Adapter for an independently acquired public caption; does not download anything.

    Caller must have acquired this exact text through an authorized public endpoint.
    The original HTML remains available but is not used as the transcript.
    """
    if not youtube_info(source.get('resolved_url') or source.get('source_url')) or not public_url(transcript_url):
        raise ValueError('invalid public caption provenance')
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('invalid caption text')
    return {**source, 'source_kind': 'youtube', 'transcript_text': text,
            'transcript_status': 'obtained', 'transcript_provenance': {'url': transcript_url, 'language': language},
            'transcript_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'retrieval_status': 'fetched'}


def download_page(url):
    chain = []
    try:
        result = _download_page(url, chain)
    except (TimeoutError, socket.timeout):
        result = {'retrieval_status': 'timeout', 'retrieval_error': 'socket_timeout'}
    except Exception as error:
        parsed_response = bool(chain and chain[-1]['http_status'] == 200)
        result = {'retrieval_status': 'unextractable' if parsed_response else 'unavailable',
                  'content_quality': 'extraction_failed' if parsed_response else 'fetch_failed',
                  'retrieval_error': type(error).__name__}
    result.update(original_url=url, redirect_chain=chain,
                  provenance={'acquisition': 'pinned_public_ip_http', 'redirect_chain': chain})
    result.setdefault('resolved_url', chain[-1]['url'] if chain else None)
    result.setdefault('http_status', chain[-1]['http_status'] if chain else None)
    result.setdefault('fetched_at', datetime.now(timezone.utc).isoformat())
    result.setdefault('content_quality', acquisition_quality(result))
    result.setdefault('extraction_status', result['retrieval_status'])
    result.setdefault('extraction_error', result.get('retrieval_error'))
    for key in ('canonical_url', 'title', 'published_at', 'article_text', 'article_text_hash'):
        result.setdefault(key, None)
    result.setdefault('source_type', 'youtube' if youtube_info(result.get('resolved_url') or url) else 'unknown')
    if urlsplit(result.get('resolved_url') or url).hostname in ('google.com', 'www.google.com', 'consent.google.com'):
        result['source_type'] = 'search_page'
    return result


def _download_page(url, chain):
    """Runs in a killable worker: pinned public IP, TLS hostname validation, no proxies."""
    for _ in range(4):
        if not public_url(url):
            return {'retrieval_status': 'blocked_url'}
        p = urlsplit(url)
        port = p.port or (443 if p.scheme == 'https' else 80)
        addresses = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not public_address(a[4][0]) for a in addresses):
            return {'retrieval_status': 'blocked_url'}
        # No second DNS resolution: connect to the exact address just checked.
        family, socktype, proto, _, address = addresses[0]
        sock = socket.socket(family, socktype, proto)
        conn = http.client.HTTPConnection(p.hostname, port, timeout=3)
        try:
            sock.settimeout(3)
            sock.connect(address)
            if p.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            conn.sock = sock
            conn.request('GET', p.path + ('?' + p.query if p.query else '') or '/',
                         headers={'User-Agent': 'WEAVE-Evidence/1.0', 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            chain.append({'url': url, 'http_status': response.status, 'location': response.getheader('Location')})
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    return {'retrieval_status': 'unavailable'}
                url = urljoin(url, location)
                continue
            if response.status != 200:
                return {'retrieval_status': 'access_denied' if response.status in (401, 403, 429) else 'unavailable', 'resolved_url': url, 'retrieval_error': f'http_{response.status}'}
            if 'text/html' not in response.getheader('Content-Type', '').lower():
                return {'retrieval_status': 'unsupported_content', 'resolved_url': url, 'retrieval_error': 'unsupported_content_or_encoding'}
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                return {'retrieval_status': 'unsupported_content', 'resolved_url': url, 'retrieval_error': 'unsupported_content_or_encoding'}
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return {'retrieval_status': 'too_large', 'resolved_url': url, 'retrieval_error': 'content_size_limit'}
            charset = response.headers.get_content_charset() or 'utf-8'
            return parse_page(body, url, charset)
        finally:
            conn.close()
            sock.close()
    return {'retrieval_status': 'redirect_limit', 'retrieval_error': 'redirect_limit_or_unresolved_grounding_redirect'}


def fetch_source(url):
    if not public_url(url):
        return {'retrieval_status': 'blocked_url'}
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--fetch'],
                              input=json.dumps(url), capture_output=True, text=True,
                              encoding='utf-8', timeout=FETCH_TIMEOUT, check=True)
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return {'retrieval_status': 'timeout'}
    except Exception:
        return {'retrieval_status': 'unavailable'}


def get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def grounding_details(response):
    candidates = get(response, 'candidates', []) or []
    metadata = get(candidates[0], 'grounding_metadata') if candidates else None
    sources, supports = [], []
    for index, chunk in enumerate(get(metadata, 'grounding_chunks', []) or []):
        web = get(chunk, 'web')
        url = get(web, 'uri')
        if not isinstance(url, str):
            continue
        sources.append({'source_id': f's{index}', 'chunk_index': index,
                        'source_title': get(web, 'title') or None,
                        'source_url': url, 'source_site': urlsplit(url).hostname if public_url(url) else None,
                        'published_date': None, 'source_excerpt': None,
                        'excerpt_provenance': None, 'retrieval_status': 'not_fetched'})
    for support in get(metadata, 'grounding_supports', []) or []:
        segment = get(support, 'segment')
        supports.append({'text': get(segment, 'text') or '',
                         'start_index': get(segment, 'start_index'),
                         'end_index': get(segment, 'end_index'),
                         'source_ids': [f's{i}' for i in (get(support, 'grounding_chunk_indices', []) or [])],
                         'provenance': 'grounding_model_response_segment'})
    return {'sources': sources, 'grounding_supports': supports}


def spans(value):
    """Only split original text; offsets retain the exact model wording."""
    if not isinstance(value, str):
        return []
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r'[^。！？\n]+[。！？]?|[。！？]', value) if m.group().strip()]


def literal_match(a, b):
    # Deliberately conservative. Shared keywords are not a citation.
    return any(len(t.strip()) >= 8 and t.strip() in b for t, _, _ in spans(a))


def article_candidate_priority(source):
    """Prefer text articles without discarding opaque Grounding redirect URLs."""
    url = source.get('source_url') or ''
    if not public_url(url):
        return 3
    parsed = urlsplit(url)
    path = parsed.path.lower()
    host = (parsed.hostname or '').lower()
    if youtube_info(url) or re.search(r'/(videos?|watch|shorts|reels?)(/|$)', path):
        return 2
    if host == 'vertexaisearch.cloud.google.com' and path.startswith('/grounding-api-redirect/'):
        # Destination is unknown until the existing safe downloader follows it.
        # Grounding titles provide only a weak hint, never a reason to discard it.
        title = (source.get('source_title') or '').lower()
        return 2 if re.search(r'\b(youtube|watch video|video clip)\b', title) else 1
    return 0


def prepare_evidence(retrieve, transcript, fetcher=fetch_source):
    sources = retrieve.get('sources', [])
    fetched, identities = {}, {}
    # Fetch in candidate-priority order, but retain Grounding's original order,
    # source IDs, citations, and all records in the returned evidence object.
    order = sorted(range(len(sources)), key=lambda i: article_candidate_priority(sources[i]))
    attempts = 0
    for index in order:
        source = sources[index]
        source.setdefault('grounding_url', source.get('source_url'))
        try:
            url = source['source_url']
            if url not in fetched:
                if youtube_info(url):
                    # YouTube HTML is not a news article or a video transcript.
                    fetched[url] = {'retrieval_status': 'content_unavailable',
                                    'source_type': 'youtube', 'source_kind': 'youtube',
                                    'transcript_status': 'not_obtained',
                                    'extraction_status': 'youtube_metadata_only',
                                    'extraction_error': 'non_article_video_source',
                                    'content_quality': 'not_attempted'}
                elif attempts < MAX_FETCHES:
                    attempts += 1  # Failed/blocked requests still count.
                    source['fetch_attempted_at'] = datetime.now(timezone.utc).isoformat()
                    fetched[url] = {'retrieval_status': 'unavailable'}
                    try:
                        fetched[url] = fetcher(url)
                    except Exception:
                        pass
                else:
                    fetched[url] = {'retrieval_status': 'budget_exceeded'}
            source.update(fetched[url])
        except Exception:
            source['retrieval_status'] = 'unavailable'
        if source.get('retrieval_status') != 'fetched':
            source.setdefault('retrieval_error', source.get('retrieval_status'))
        if public_url(source.get('resolved_url')):
            source['source_site'] = urlsplit(source['resolved_url']).hostname
        source.setdefault('original_url', source.get('source_url'))
        source.setdefault('content_quality', acquisition_quality(source))
        source.setdefault('extraction_status', source.get('retrieval_status'))
        source.setdefault('extraction_error', source.get('retrieval_error'))
        source.setdefault('source_type', 'unknown')
        source.setdefault('provenance', {'acquisition': 'not_obtained'})
        for key in ('canonical_url', 'title', 'published_at', 'fetched_at', 'article_text', 'article_text_hash'):
            source.setdefault(key, None)
    # Deduplication must use original Grounding order, not fetch priority.
    for source in sources:
        identity = source.get('article_id') or source.get('resolved_url') or source.get('source_url')
        source['duplicate_of'] = identities.get(identity)
        identities.setdefault(identity, source['source_id'])
    return {'schema_version': 1, 'video_id': retrieve.get('vid'),
            'analysis_id': retrieve.get('analysis_id'), 'run_id': retrieve.get('run_id'),
            'sources': sources, 'grounding_supports': retrieve.get('grounding_supports', []),
            'original_input': {'transcript': transcript or None, 'video_timestamp': None,
                               'timing_status': 'not_aligned'}, 'claims': [], 'reasons': []}


def build_links(retrieve, reason):
    import copy
    evidence = copy.deepcopy(retrieve.get('evidence') or {})
    if not evidence or evidence.get('video_id') != retrieve.get('vid') or evidence.get('analysis_id') != retrieve.get('analysis_id'):
        return None
    claims = []
    for field in ('Rc', 'Rv'):
        for text, start, end in spans(retrieve.get(field)):
            claims.append({'claim_id': f'c{len(claims)}', 'claim_text': text,
                           'claim_provenance': {'field': field, 'start': start, 'end': end}, 'evidence': []})
    sources = evidence.get('sources', [])
    supports = evidence.get('grounding_supports', [])
    for claim in claims:
        for source in sources:
            text = source.get('source_text') or ''
            needle = claim['claim_text'].strip()
            pos = text.find(needle) if len(needle) >= 8 else -1
            grounded = any(source['source_id'] in s['source_ids'] and literal_match(needle, s['text']) for s in supports)
            if pos >= 0 or grounded:
                claim['evidence'].append({'source_id': source['source_id'],
                    'evidence_relation': 'insufficient',
                    'match_basis': 'literal_article_text' if pos >= 0 else 'grounding_segment',
                    'source_excerpt': text[pos:pos + len(needle)] if pos >= 0 else None,
                    'excerpt_provenance': {'field': 'source_text', 'start': pos, 'end': pos + len(needle),
                                           'content_sha256': source.get('content_sha256')} if pos >= 0 else None})
    reasons = []
    transcript = evidence.get('original_input', {}).get('transcript') or ''
    for text, start, end in spans(reason):
        related = [c for c in claims if literal_match(c['claim_text'], text) or literal_match(text, c['claim_text'])]
        direct = []
        for source in sources:
            # Grounding maps retrieval response text, NOT the student's judgment.
            if any(source['source_id'] in s['source_ids'] and literal_match(s['text'], text) for s in supports):
                direct.append({'source_id': source['source_id'], 'evidence_relation': 'background',
                               'match_basis': 'literal_grounding_text', 'source_excerpt': None,
                               'excerpt_provenance': None})
        excerpt = next((c['claim_text'].strip() for c in related if c['claim_text'].strip() in transcript), None)
        reasons.append({'reason_id': f'r{len(reasons)}', 'reason_text': text,
                        'reason_provenance': {'field': 'reason', 'start': start, 'end': end},
                        'claim_ids': [c['claim_id'] for c in related], 'evidence': direct,
                        'video_timestamp': None, 'transcript_excerpt': excerpt,
                        'timing_status': 'not_aligned'})
    evidence.update(claims=claims, reasons=reasons)
    return evidence


if __name__ == '__main__' and sys.argv[1:] == ['--fetch']:
    try:
        result = download_page(json.loads(sys.stdin.read()))
    except Exception:
        result = {'retrieval_status': 'unavailable'}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
