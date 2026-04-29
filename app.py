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
function log(message) {
    const result = document.getElementById("result");
    const timestamp = new Date().toLocaleTimeString();
    result.textContent += `[${timestamp}] ${message}\n`;
}

async function submitCalculation() {
    const result = document.getElementById("result");
    result.textContent = "";

    log("Submit clicked");
    log("Round-trip 1 starting: requesting attestation from backend");
    log("No numbers have been sent yet");

    const attestResponse = await fetch("/attest", {
        method: "POST"
    });

    const attestData = await attestResponse.json();

    log("Attestation response received from backend");
    log("HTTP status: " + attestResponse.status);
    log("Backend message: " + attestData.message);

    if (attestData.details) {
        log("AttestationClient output:");
        log(attestData.details);
    }

    if (!attestResponse.ok) {
        log("STOP: Attestation failed. Numbers will NOT be sent.");
        return;
    }

    log("Attestation succeeded");
    log("Temporary attestation token received");
    log("Round-trip 2 starting: sending numbers for calculation");

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

    log("Calculation response received from backend");
    log("HTTP status: " + multiplyResponse.status);

    if (!multiplyResponse.ok) {
        log("Calculation denied: " + multiplyData.message);
        return;
    }

    log("Calculation allowed");
    log("Result: " + multiplyData.result);
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
    print("\n==================================================")
    print("[ATTEST] New attestation request received")

    if not ATTESTATION_URI:
        print("[ATTEST] ERROR: ATTESTATION_URI is not configured")
        return jsonify({
            "status": "failed",
            "message": "ATTESTATION_URI environment variable is not configured."
        }), 500

    print(f"[ATTEST] Using attestation endpoint: {ATTESTATION_URI}")
    print(f"[ATTEST] Executing binary: {ATTESTATION_BINARY}")

    try:
        command = [
            "sudo",
            ATTESTATION_BINARY,
            "-a",
            ATTESTATION_URI
        ]

        print(f"[ATTEST] Running command: {' '.join(command)}")
        print("[ATTEST] Starting attestation now...")

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60
        )

        output = result.stdout + result.stderr

        print(f"[ATTEST] Return code: {result.returncode}")

        if result.stdout:
            print("\n[ATTEST] STDOUT:")
            print(result.stdout[-2000:])

        if result.stderr:
            print("\n[ATTEST] STDERR:")
            print(result.stderr[-2000:])

        if result.returncode != 0:
            print("[ATTEST] FAILED: AttestationClient returned non-zero exit code")
            print("==================================================\n")

            return jsonify({
                "status": "failed",
                "message": "AttestationClient returned an error.",
                "details": output[-1000:]
            }), 403

        print("[ATTEST] SUCCESS: CVM attestation completed successfully")

        token = secrets.token_urlsafe(32)
        TOKENS[token] = time.time() + TOKEN_TTL_SECONDS

        print(f"[ATTEST] Temporary token created (valid {TOKEN_TTL_SECONDS}s)")
        print("==================================================\n")

        return jsonify({
            "status": "success",
            "message": "CVM attestation succeeded.",
            "attestationToken": token,
            "details": output[-2000:]
        })

    except subprocess.TimeoutExpired:
        print("[ATTEST] FAILED: Attestation timed out")
        print("==================================================\n")

        return jsonify({
            "status": "failed",
            "message": "Attestation timed out."
        }), 504

    except Exception as e:
        print(f"[ATTEST] FAILED: Exception occurred: {str(e)}")
        print("==================================================\n")

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