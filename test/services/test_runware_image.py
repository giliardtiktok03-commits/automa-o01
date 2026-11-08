import hashlib
import json
from unittest.mock import patch
from uuid import uuid4
import pytest
from app.models.schema import VideoParams
from app.services import runware_image as rw

def test_removed_runware_cannot_submit_new_paid_request(tmp_path):
    params=VideoParams(video_subject="History")
    with patch.dict(rw.config.app, {"runware_api_key":"local-test"}), patch.object(rw.Client,"post") as post:
        with pytest.raises(rw.RunwareError,match="removida"):
            rw.generate(params,"Historic scene",tmp_path)
    post.assert_not_called()

def test_already_paid_runware_image_remains_reusable(tmp_path):
    params=VideoParams(video_subject="History")
    with patch.dict(rw.config.app, {"runware_api_key":"local-test"}), patch.object(rw.Client,"post") as post:
        rw.freeze(params)
        spec={**rw.parameters(params),"positivePrompt":"Historic scene"}
        state={"version":1,"fingerprint":hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest(),
               "task_id":str(uuid4()),"status":"saved","sha256":hashlib.sha256(b"paid image").hexdigest()}
        (tmp_path/"runware-image.json").write_text(json.dumps(state))
        (tmp_path/"image.png").write_bytes(b"paid image")
        image,_=rw.generate(params,"Historic scene",tmp_path,existing_only=True)
        assert image.read_bytes()==b"paid image"
    post.assert_not_called()
