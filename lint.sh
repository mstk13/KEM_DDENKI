pip install -q ruff
ruff check . --select E501 --output-format concise > /rel/e501.txt
