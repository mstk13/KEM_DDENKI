FROM python:3.12-slim

WORKDIR /app

# 全アプリの requirements.txt をコピー
COPY bid_manager/requirements.txt /tmp/req-bid.txt
COPY material_manager/requirements.txt /tmp/req-mat.txt
COPY sagyo-nippou/requirements.txt /tmp/req-nip.txt
COPY evaluation/requirements.txt /tmp/req-eval.txt
COPY eigyo-kanri/requirements.txt /tmp/req-eigyo.txt
COPY nippou-kanri/requirements.txt /tmp/req-nkanri.txt

RUN pip install --no-cache-dir \
    -r /tmp/req-bid.txt \
    -r /tmp/req-mat.txt \
    -r /tmp/req-nip.txt \
    -r /tmp/req-eval.txt \
    -r /tmp/req-eigyo.txt \
    -r /tmp/req-nkanri.txt \
    'psycopg2-binary>=2.9,<3.0' \
    'anthropic>=0.40,<1.0' \
    && rm /tmp/req-*.txt

# アプリ全体をコピー
COPY . /app

# エントリポイント
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
