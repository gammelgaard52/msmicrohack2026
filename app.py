from flask import Flask, request, jsonify, render_template_string
import subprocess
import secrets
import time
import os

app = Flask(__name__)

ATTESTATION_BINARY = "/opt/cvm-attestation/AttestationClient"
ATTESTATION_URI = os.environ.get("ATTESTATION_URI")

TOKENS = {}
TOKEN_TTL_SECONDS = 60

HTML = """
<!doctype html>
<html>
<head>
    <title>Confidential Multiply</title>
</head>
<body>
    <h2>Confidential Multiply</h2>

    <input id="a" type="number" placeholder="First number">
    <input id="b" type="number" placeholder="Second number">
    <button onclick="submitCalculation()">Submit</button>

    <pre id="result"></pre>

<script>
async function submitCalculation() {
    const result = document.getElementById("result");
    result.textContent = "Running attestation...";

    const attestResponse = await fetch("/attest", {
        method: "POST"
    });

    const attestData = await attestResponse.json();

    if (!attestResponse.ok) {
        result.textContent = "Attestation failed: " + attestData.message;
        return;
    }

    result.textContent = "Attestation succeeded. Sending numbers...";

    const multiplyResponse = await fetch("/multiply", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            a: document.getElementById("a").value,
            b: document.getElementById("b").value,
            attestationToken: attestData.attestationToken
        })
    });

    const multiplyData = await multiplyResponse.json();

    if (!multiplyResponse.ok) {
        result.textContent = "Calculation denied: " + multiplyData.message;
        return;
    }

    result.textContent = "Result: " + multiplyData.result;
}
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML)

@app.route("/attest", methods=["POST"])
def attest():
    if not ATTESTATION_URI:
        return jsonify({
            "status": "failed",
            "message": "ATTESTATION_URI environment variable is not configured."
        }), 500

    try:
        result = subprocess.run(
            [
                "sudo",
                ATTESTATION_BINARY,
                "-a",
                ATTESTATION_URI
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        output = result.stdout + result.stderr

        if result.returncode != 0:
            return jsonify({
                "status": "failed",
                "message": "AttestationClient returned an error.",
                "details": output[-1000:]
            }), 403

        token = secrets.token_urlsafe(32)
        TOKENS[token] = time.time() + TOKEN_TTL_SECONDS

        return jsonify({
            "status": "success",
            "message": "CVM attestation succeeded.",
            "attestationToken": token
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "failed",
            "message": "Attestation timed out."
        }), 504

    except Exception as e:
        return jsonify({
            "status": "failed",
            "message": f"Attestation execution failed: {str(e)}"
        }), 500

@app.route("/multiply", methods=["POST"])
def multiply():
    data = request.get_json()

    if not data:
        return jsonify({
            "message": "Missing JSON body."
        }), 400

    token = data.get("attestationToken")

    if token not in TOKENS:
        return jsonify({
            "message": "Missing or invalid attestation token."
        }), 403

    if TOKENS[token] < time.time():
        TOKENS.pop(token, None)
        return jsonify({
            "message": "Attestation token expired."
        }), 403

    TOKENS.pop(token, None)

    try:
        a = float(data.get("a"))
        b = float(data.get("b"))

        return jsonify({
            "result": a * b
        })

    except Exception:
        return jsonify({
            "message": "Invalid numbers."
        }), 400

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=443,
        ssl_context=("certs/cert.pem", "certs/key.pem")
    )