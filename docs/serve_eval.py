"""人事評価草案の編集サーバー（保存機能付き）"""
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluation_draft.html")

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/save":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with open(FILE_PATH, "wb") as f:
                f.write(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("OK".encode())
            print(f"[保存完了] {FILE_PATH}")
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("人事評価草案エディタ起動中: http://localhost:8080/evaluation_draft.html")
    print("Ctrl+C で停止")
    server.serve_forever()
