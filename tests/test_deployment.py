"""Web deployment smoke tests; no AI calls or writes to existing runtime data.

Run from the project root: python -m unittest discover -s tests -v
Only Flask, flask-cors and python-dotenv are required.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
import database


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        # The translation client otherwise requires credentials at import time.
        translation = patch.dict(sys.modules, {"translator": SimpleNamespace(
            translate_to_english=lambda texts: {key: 'translated' for key in texts})})
        translation.start()
        self.addCleanup(translation.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Importing vote_api initializes storage. Redirect it before importing app.
        for name, value in {
            "DATA_DIR": str(self.root / "data"),
            "VOTE_DATA_PATH": str(self.root / "data" / "votes.json"),
        }.items():
            mock = patch.object(database, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.original_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.original_cwd)

    def load_app(self, **env):
        config = os.environ.copy()
        for key in ("APP_ENV", "CORS_ALLOWED_ORIGINS", "FLASK_HOST", "FLASK_PORT", "FLASK_DEBUG"):
            config.pop(key, None)
        config.update(env)
        spec = importlib.util.spec_from_file_location("deployment_app", BACKEND / "app.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, config, clear=True), patch("dotenv.load_dotenv") as dotenv:
            spec.loader.exec_module(module)
        dotenv.assert_called_once_with(str(BACKEND.parent / ".env"), override=False)
        self.addCleanup(module.executor.shutdown, wait=True)
        return module

    def test_routes_and_absolute_paths_from_unrelated_cwd(self):
        module = self.load_app()
        routes = {rule.rule: rule.methods for rule in module.app.url_map.iter_rules()}
        for path, method in {
            "/upload": "POST", "/status": "GET", "/result": "GET",
            "/student_result": "GET", "/vote": "POST", "/vote/statistics": "GET",
        }.items():
            self.assertIn(method, routes[path])
        self.assertEqual(Path(module.UPLOAD_FOLDER), BACKEND / "uploads")
        self.assertEqual(Path(module.OUTPUT_DIR), BACKEND / "output")
        self.assertEqual(Path(module.ANSWER_PATH), BACKEND.parent / "answer.jsonl")
        import pipeline
        self.assertEqual(Path(pipeline.BASE_DIR), BACKEND)
        self.assertTrue(Path(database.VOTE_DATA_PATH).is_absolute())

    def test_upload_poll_results_and_votes(self):
        module = self.load_app()
        module.UPLOAD_FOLDER = str(self.root)
        module.OUTPUT_DIR = str(self.root)
        module.answer_index = {"sample": 0}
        module.process_status = {"filename": "sample.mp4"}
        client = module.app.test_client()
        for path in ('/upload', '/status', '/result', '/student_result'):
            response = client.post(path) if path == '/upload' else client.get(path)
            self.assertEqual(response.status_code, 410)
            self.assertNotIn('correct_answer', response.json)
        self.assertEqual(client.post("/vote", json={}).status_code, 400)
        response = client.post("/vote", json={"video_id": "sample.mp4", "vote": "true"})
        self.assertEqual(response.status_code, 201)
        stats = client.get("/vote/statistics?video_id=sample.mp4").json
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["true_percent"], 100)

    def test_development_cors(self):
        client = self.load_app().app.test_client()
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"):
            response = client.get("/status", headers={"Origin": origin})
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
        response = client.get("/status", headers={"Origin": "https://unlisted.example"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_production_cors_defaults_closed(self):
        client = self.load_app(APP_ENV="production").app.test_client()
        for origin in ("http://localhost:5173", "https://domain.com"):
            self.assertNotIn("Access-Control-Allow-Origin", client.get("/status", headers={"Origin": origin}).headers)

    def test_explicit_origins_and_vote_preflight(self):
        client = self.load_app(APP_ENV="production", CORS_ALLOWED_ORIGINS="https://domain.com, https://second.example/").app.test_client()
        for origin in ("https://domain.com", "https://second.example"):
            response = client.options("/vote", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
            self.assertIn("Content-Type", response.headers["Access-Control-Allow-Headers"])
        for origin in ("https://domainXcom", "https://domain.com.evil.example", "http://localhost:5173"):
            self.assertNotIn("Access-Control-Allow-Origin", client.get("/status", headers={"Origin": origin}).headers)

    def test_wildcard_rejected(self):
        with self.assertRaises(ValueError):
            self.load_app(APP_ENV="production", CORS_ALLOWED_ORIGINS="*")

    def test_development_server_settings(self):
        for mode, expected_debug in (("development", True), ("production", False)):
            with patch.dict(os.environ, {"APP_ENV": mode, "FLASK_HOST": "0.0.0.0", "FLASK_PORT": "5055", "FLASK_DEBUG": "1", "CORS_ALLOWED_ORIGINS": ""}), patch("dotenv.load_dotenv"), patch("flask.Flask.run") as run:
                namespace = runpy.run_path(str(BACKEND / "app.py"), run_name="__main__")
            namespace["executor"].shutdown(wait=True)
            run.assert_called_once_with(host="0.0.0.0", port=5055, debug=expected_debug, use_reloader=False)


if __name__ == "__main__":
    unittest.main()
