#!/usr/bin/env python3
"""GitHub Webhook レシーバー。

developerブランチへのpushを検知して自動デプロイを実行する。
軽量な標準ライブラリのみで動作（Flask不要）。

使い方:
    # シークレットを設定して起動
    WEBHOOK_SECRET=your-secret-here python receiver.py

    # バックグラウンドで起動
    WEBHOOK_SECRET=your-secret-here nohup python receiver.py &

    # systemd サービスとして起動（推奨）
    sudo systemctl start kem-webhook

ポート: 9000（デフォルト）
エンドポイント: POST /webhook
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# 設定
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
LISTEN_PORT = int(os.environ.get("WEBHOOK_PORT", "9000"))
TARGET_BRANCH = os.environ.get("TARGET_BRANCH", "refs/heads/developer")
DEPLOY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy.sh")
LOG_FILE = os.environ.get("WEBHOOK_LOG", "/tmp/kem-webhook.log")

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """GitHub webhookの署名を検証する。"""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET が未設定です。署名検証をスキップします。")
        return True

    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def run_deploy():
    """デプロイスクリプトを実行する。"""
    logger.info("デプロイスクリプトを実行中: %s", DEPLOY_SCRIPT)
    try:
        result = subprocess.run(
            ["bash", DEPLOY_SCRIPT],
            capture_output=True,
            text=True,
            timeout=300,
        )
        logger.info("デプロイ完了 (exit code: %d)", result.returncode)
        if result.stdout:
            logger.info("stdout: %s", result.stdout[-500:])
        if result.returncode != 0 and result.stderr:
            logger.error("stderr: %s", result.stderr[-500:])
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("デプロイがタイムアウトしました（300秒）")
        return False
    except Exception as e:
        logger.error("デプロイ実行エラー: %s", e)
        return False


class WebhookHandler(BaseHTTPRequestHandler):
    """GitHub Webhook HTTPハンドラー。"""

    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        payload_body = self.rfile.read(content_length)

        # 署名検証
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(payload_body, signature):
            logger.warning("署名検証に失敗しました")
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"error": "invalid signature"}')
            return

        # イベント種別チェック
        event = self.headers.get("X-GitHub-Event", "")
        if event != "push":
            logger.info("pushイベントではないためスキップ: %s", event)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ignored", "reason": "not a push event"}')
            return

        # ペイロード解析
        try:
            payload = json.loads(payload_body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        ref = payload.get("ref", "")
        pusher = payload.get("pusher", {}).get("name", "unknown")

        # ブランチチェック
        if ref != TARGET_BRANCH:
            logger.info("対象ブランチではないためスキップ: %s (対象: %s)", ref, TARGET_BRANCH)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "ignored", "reason": f"branch {ref} is not target"}).encode()
            )
            return

        # デプロイ実行
        logger.info("=== デプロイ開始 === pusher: %s, branch: %s", pusher, ref)
        success = run_deploy()

        status = "success" if success else "failed"
        logger.info("=== デプロイ%s ===", "成功" if success else "失敗")

        self.send_response(200 if success else 500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": status, "branch": ref, "pusher": pusher}).encode()
        )

    def do_GET(self):
        """ヘルスチェック用。"""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "status": "ok",
                    "target_branch": TARGET_BRANCH,
                    "port": LISTEN_PORT,
                }).encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """デフォルトのアクセスログを抑制（logging で管理）。"""
        pass


def main():
    if not WEBHOOK_SECRET:
        logger.warning(
            "!!! WEBHOOK_SECRET が未設定です。本番では必ず設定してください !!!\n"
            "  export WEBHOOK_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
        )

    server = HTTPServer(("0.0.0.0", LISTEN_PORT), WebhookHandler)
    logger.info("Webhook レシーバー起動: port=%d, target=%s", LISTEN_PORT, TARGET_BRANCH)
    logger.info("ヘルスチェック: http://localhost:%d/health", LISTEN_PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("シャットダウン")
        server.server_close()


if __name__ == "__main__":
    main()
