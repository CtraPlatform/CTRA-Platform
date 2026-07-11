from flask import Flask, request, jsonify
from tabpfn_ctra_new import main
import secrets

app = Flask(__name__)

# 固定 Token（生产环境建议放环境变量）
API_TOKEN = "c31a5523beacdcac42ef089fb3e85d676faa76026b813c0b351fb0faca7387eb"


def check_token():
    """验证请求中的 Token"""
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    return token == API_TOKEN


@app.route("/trigger", methods=["GET", "POST"])
def trigger():
    # Token 验证
    if not check_token():
        return jsonify({"success": False, "error": "无效或缺少 Token"}), 401

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        ids = data.get("ids")
    else:
        ids = request.args.getlist("ids")

    if not ids:
        return jsonify({"success": False, "error": "缺少参数 ids"}), 400

    if isinstance(ids, str):
        ids = [ids]

    try:
        results = {}
        print(ids)
        results = main(ids)
        return jsonify({"success": True, "ids": ids, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=True)