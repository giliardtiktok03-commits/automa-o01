import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
import requests

from app.services.ai33 import AI33Client, AI33Error, ImageJob
from app.services.ai33.images import download_png, _public_https


PARAMS = {"aspect_ratio": "16:9", "resolution": "2K"}
MODEL = {"model_id": "documented-model", "requires_reference_images": False,
         "aspect_ratios": ["16:9"], "resolutions": ["2K"], "max_generations": 4}


def response(payload=None, status=200):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.json.return_value = payload
    return result


class AI33ContractTests(unittest.TestCase):
    def setUp(self):
        self.client = AI33Client("private-test-key")

    @patch("app.services.ai33.client.requests.request")
    def test_catalog_validation_uses_real_catalog(self, request):
        request.return_value = response({"success": True, "models": [MODEL]})
        self.client.validate("documented-model", PARAMS, "Historical illustration")
        self.assertEqual(request.call_args.args, ("GET", "https://api.ai33.pro/v1i/models"))
        for params in ({**PARAMS, "resolution": "invented"}, {**PARAMS, "extra": True}):
            with self.assertRaises(AI33Error):
                self.client.validate("documented-model", params, "test")
        with self.assertRaises(AI33Error):
            self.client.validate("missing", PARAMS, "test")

    @patch("app.services.ai33.client.requests.request")
    def test_multipart_and_exact_endpoints(self, request):
        request.side_effect = [response({"success": True, "credits": 12}),
                               response({"success": True, "task_id": "abc-123"})]
        self.assertEqual(self.client.price("documented-model", PARAMS), 12)
        self.assertEqual(self.client.submit("documented-model", PARAMS, "test"), "abc-123")
        quote, submit = request.call_args_list
        self.assertEqual(quote.args[1], "https://api.ai33.pro/v1i/task/price")
        self.assertEqual(quote.kwargs["json"]["assets"], 0)
        self.assertEqual(submit.args[1], "https://api.ai33.pro/v1i/task/generate-image")
        self.assertEqual(submit.kwargs["files"]["generations_count"], (None, "1"))
        self.assertEqual(json.loads(submit.kwargs["files"]["model_parameters"][1]), PARAMS)
        self.assertFalse(submit.kwargs["allow_redirects"])
        self.assertEqual(submit.kwargs["headers"], {"xi-api-key": "private-test-key"})

    @patch("app.services.ai33.client.requests.request")
    def test_errors_do_not_expose_key_or_retry(self, request):
        for error in (requests.Timeout("private-test-key"), ValueError("private-test-key")):
            request.reset_mock()
            request.side_effect = error
            with self.assertRaises(AI33Error) as caught:
                self.client.submit("documented-model", PARAMS, "test")
            self.assertNotIn("private-test-key", str(caught.exception))
            self.assertEqual(request.call_count, 1)
        request.side_effect = None
        for status in (301, 400, 401, 422, 429, 500):
            request.return_value = response(status=status)
            with self.assertRaisesRegex(AI33Error, str(status)):
                self.client.models()

    @patch("app.services.ai33.client.requests.request")
    def test_invalid_credits_and_task_identity(self, request):
        for value in (None, True, -1, float("nan"), "12"):
            request.return_value = response({"success": True, "credits": value})
            with self.assertRaises(AI33Error):
                self.client.price("model", PARAMS)
        for payload in ({"id": "other", "type": "imagen2", "status": "done"},
                        {"id": "abc", "type": "imagen2", "status": "unknown"},
                        {"id": "abc", "type": "speech", "status": "done"}):
            request.return_value = response(payload)
            with self.assertRaises(AI33Error):
                self.client.task("abc")
        request.reset_mock()
        with self.assertRaises(AI33Error):
            self.client.task("../danger")
        request.assert_not_called()

    @patch("app.services.ai33.client.time.sleep")
    @patch("app.services.ai33.client.requests.request")
    def test_task_503_retries_same_get_then_recovers(self, request, sleep):
        busy = response(status=503)
        busy.headers = {"Retry-After": "6"}
        done = {"id": "abc", "type": "imagen2", "status": "done"}
        request.side_effect = [busy, response(done)]
        self.assertEqual(self.client.task("abc"), done)
        sleep.assert_called_once_with(6)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(c.args == ("GET", "https://api.ai33.pro/v1/task/abc")
                            for c in request.call_args_list))

    @patch("app.services.ai33.client.time.sleep")
    @patch("app.services.ai33.client.requests.request")
    def test_task_retry_bound_and_long_retry_after(self, request, sleep):
        busy = response(status=503)
        busy.headers = {}
        request.return_value = busy
        with self.assertRaisesRegex(AI33Error, "tarefa preservada"):
            self.client.task("abc")
        self.assertEqual(request.call_count, 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [4, 8, 16])
        request.reset_mock()
        sleep.reset_mock()
        busy.headers = {"Retry-After": "120"}
        with self.assertRaises(AI33Error):
            self.client.task("abc")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    @patch("app.services.ai33.client.time.sleep")
    @patch("app.services.ai33.client.requests.request")
    def test_task_transport_retry_but_paid_503_is_never_retried(self, request, sleep):
        request.side_effect = [requests.Timeout("private-test-key"),
                               response({"id": "abc", "type": "imagen2", "status": "doing"})]
        self.client.task("abc")
        self.assertEqual(request.call_count, 2)
        request.reset_mock()
        sleep.reset_mock()
        request.side_effect = None
        request.return_value = response(status=503)
        with self.assertRaises(AI33Error):
            self.client.submit("model", PARAMS, "test")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    @patch("app.services.ai33.client.time.sleep")
    @patch("app.services.ai33.client.requests.request")
    def test_permanent_auth_error_and_invalid_json_are_not_retried(self, request, sleep):
        request.return_value = response(status=401)
        with self.assertRaises(AI33Error):
            self.client.task("abc")
        self.assertEqual(request.call_count, 1)
        request.reset_mock()
        invalid = response()
        invalid.json.side_effect = ValueError("private-test-key")
        request.return_value = invalid
        with self.assertRaises(AI33Error):
            self.client.task("abc")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()


class AI33ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = MagicMock()
        self.client.price.return_value = 12
        self.client.submit.return_value = "abc"
        self.client.task.return_value = {"status": "done", "credit_cost": 12,
                                       "metadata": {"result_images": [{"imageUrl": "https://cdn.example/image"}]}}
        self.kwargs = dict(model_id="model", parameters=PARAMS, prompt="illustration", max_credits=12)

    def job(self):
        return ImageJob(self.client, self.temp.name)

    def test_quote_cap_stops_before_submission(self):
        callback = MagicMock()
        with self.assertRaises(AI33Error):
            self.job().run(**{**self.kwargs, "max_credits": 11}, before_submit=callback)
        self.client.submit.assert_not_called()
        callback.assert_not_called()
        self.assertFalse((Path(self.temp.name) / "ai33-image.json").exists())

    @patch("app.services.ai33.images.download_png", return_value=b"png")
    def test_submission_callback_runs_after_intent_before_post_and_not_on_resume(self, download):
        def before():
            state = json.loads(self.job().checkpoint.read_text())
            self.assertEqual(state["status"], "submission_unconfirmed")
            self.client.submit.assert_not_called()
        callback = MagicMock(side_effect=before)
        self.job().run(**self.kwargs, before_submit=callback)
        self.job().run(**self.kwargs, before_submit=callback)
        callback.assert_called_once()
        self.assertEqual(self.client.submit.call_count, 1)

    def test_lost_submission_response_never_reposts(self):
        def lost(*args):
            checkpoint = json.loads((Path(self.temp.name) / "ai33-image.json").read_text())
            self.assertEqual(checkpoint["status"], "submission_unconfirmed")
            raise AI33Error("timeout")
        self.client.submit.side_effect = lost
        for _ in range(2):
            with self.assertRaises(AI33Error):
                self.job().run(**self.kwargs)
        self.assertEqual(self.client.submit.call_count, 1)

    @patch("app.services.ai33.images.download_png")
    def test_download_retry_restart_integrity_and_changed_request(self, download):
        download.side_effect = [AI33Error("download failed"), b"png", b"recovered"]
        with self.assertRaises(AI33Error):
            self.job().run(**self.kwargs)
        path = self.job().run(**self.kwargs)
        self.assertEqual(path.read_bytes(), b"png")
        self.job().run(**self.kwargs)
        self.assertEqual(download.call_count, 2)
        path.write_bytes(b"corrupt")
        self.job().run(**self.kwargs)
        self.assertEqual(path.read_bytes(), b"recovered")
        self.assertEqual(self.client.submit.call_count, 1)
        with self.assertRaises(AI33Error):
            self.job().run(**{**self.kwargs, "prompt": "different"})
        checkpoint = (Path(self.temp.name) / "ai33-image.json").read_text()
        self.assertNotIn("https://", checkpoint)
        self.assertNotIn("illustration", checkpoint)

    @patch("app.services.ai33.images.time.sleep")
    def test_poll_timeout_resumes_known_task(self, sleep):
        self.client.task.return_value = {"status": "doing"}
        with self.assertRaises(AI33Error):
            self.job().run(**self.kwargs, max_polls=2)
        sleep.assert_called_once_with(4)
        with self.assertRaises(AI33Error):
            self.job().run(**self.kwargs, max_polls=1)
        self.assertEqual(self.client.submit.call_count, 1)

    def test_remote_failure_not_classified_as_refusal_or_reposted(self):
        self.client.task.return_value = {"status": "error", "error_message": "unclassified"}
        for _ in range(2):
            with self.assertRaises(AI33Error):
                self.job().run(**self.kwargs)
        self.assertEqual(self.client.submit.call_count, 1)
        self.assertEqual(self.client.task.call_count, 1)

    def test_completed_task_without_valid_metadata_never_reposts(self):
        for metadata in (None, "invalid", {}, {"result_images": []}):
            self.client.task.return_value = {"status": "done", "metadata": metadata}
            with self.assertRaises(AI33Error):
                self.job().run(**self.kwargs)
        self.assertEqual(self.client.submit.call_count, 1)

    def test_parallel_job_cannot_submit_while_lock_is_held(self):
        from filelock import FileLock, Timeout
        job = self.job()
        with FileLock(str(job.checkpoint) + ".lock", timeout=0):
            with self.assertRaises(Timeout):
                job.run(**self.kwargs)
        self.client.submit.assert_not_called()

    @patch("app.services.ai33.client.time.sleep")
    @patch("app.services.ai33.client.requests.request")
    def test_persisted_task_503_resume_only_queries_and_keeps_checkpoint(self, request, sleep):
        self.client.task.side_effect = AI33Error("first query unavailable")
        with self.assertRaises(AI33Error):
            self.job().run(**self.kwargs)
        before = self.job().checkpoint.read_bytes()
        busy = response(status=503)
        busy.headers = {}
        request.return_value = busy
        real_job = ImageJob(AI33Client("private-test-key"), self.temp.name)
        with self.assertRaisesRegex(AI33Error, "tarefa preservada"):
            real_job.run(**self.kwargs)
        self.assertEqual(real_job.checkpoint.read_bytes(), before)
        self.assertEqual(request.call_count, 4)
        self.assertTrue(all(c.args[0] == "GET" for c in request.call_args_list))
        self.assertEqual(self.client.submit.call_count, 1)


class AI33DownloadTests(unittest.TestCase):
    def test_private_or_non_https_urls_are_rejected(self):
        for url in ("http://example.com/a", "https://user:pass@example.com/a", "https://example.com:8000/a", None):
            with self.assertRaises(AI33Error):
                _public_https(url)
        with patch("app.services.ai33.images.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(AI33Error):
                _public_https("https://example.com/a")

    @patch("app.services.ai33.images._public_https")
    @patch("app.services.ai33.images.requests.get")
    def test_download_validates_image_and_does_not_send_api_headers(self, get, validate):
        output = io.BytesIO()
        Image.new("RGB", (16, 9)).save(output, "PNG")
        redirect = response(status=302)
        redirect.headers = {"Location": "https://other.example/result"}
        image = response()
        image.iter_content.return_value = [output.getvalue()]
        get.side_effect = [redirect, image]
        self.assertTrue(download_png("https://example.com/a").startswith(b"\x89PNG"))
        self.assertEqual(validate.call_count, 2)
        for call in get.call_args_list:
            self.assertNotIn("headers", call.kwargs)
            self.assertFalse(call.kwargs["allow_redirects"])
        get.side_effect = None
        image.iter_content.return_value = [b"not an image"]
        get.return_value = image
        with self.assertRaises(AI33Error):
            download_png("https://example.com/a")


if __name__ == "__main__":
    unittest.main()
