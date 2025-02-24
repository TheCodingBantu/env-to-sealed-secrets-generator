import os
import subprocess
import yaml
import re
from flask import Flask, request, render_template, send_file
from kubernetes import client, config

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load Kubernetes config and fetch available namespaces
def get_kubernetes_namespaces():
    try:
        config.load_kube_config()  # Use kubeconfig if running locally
        v1 = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in v1.list_namespace().items]
        return namespaces
    except Exception:
        return ["default"]  # Fallback if unable to connect to cluster

# Validate .env content
def validate_env(env_content):
    lines = env_content.strip().split("\n")
    env_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")  # Format: KEY=VALUE
    seen_keys = set()

    for line in lines:
        if not line or line.startswith("#"):  # Allow comments and empty lines
            continue
        if not env_pattern.match(line):
            return f"❌ Invalid format: {line}"
        key = line.split("=")[0]
        if key in seen_keys:
            return f"❌ Duplicate key: {key}"
        seen_keys.add(key)

    return None  # No errors

@app.route("/", methods=["GET", "POST"])
def index():
    namespaces = get_kubernetes_namespaces()

    if request.method == "POST":
        env_content = request.form.get("env_content", "").strip()
        namespace = request.form.get("namespace", "default")

        if not env_content:
            return "❌ Error: No input provided", 400

        # Validate env input
        validation_error = validate_env(env_content)
        if validation_error:
            return render_template("index.html", namespaces=namespaces, error_message=validation_error)

        # Save env content to a temp file
        env_file_name = "custom-env"
        env_file_path = os.path.join(UPLOAD_FOLDER, env_file_name)
        with open(env_file_path, "w") as f:
            f.write(env_content)

        secret_name = f"{env_file_name}-secret"
        secret_yaml_path = os.path.join(UPLOAD_FOLDER, f"{secret_name}.yaml")
        sealed_yaml_path = os.path.join(UPLOAD_FOLDER, f"{secret_name}-sealed.yaml")

        try:
            # Create Kubernetes Secret
            subprocess.run(
                [
                    "kubectl", "create", "secret", "generic", secret_name,
                    f"--from-file={env_file_path}",
                    "--dry-run=client", "-o", "yaml"
                ],
                check=True,
                stdout=open(secret_yaml_path, "w"),
            )

            # Seal the Secret
            with open(secret_yaml_path, "rb") as secret_yaml:
                subprocess.run(
                    ["kubeseal", "--format", "yaml"],
                    stdin=secret_yaml,
                    stdout=open(sealed_yaml_path, "w"),
                    check=True,
                )

            # Load and format the sealed secret
            with open(sealed_yaml_path, "r") as sealed_yaml_file:
                sealed_secret_yaml = yaml.safe_load(sealed_yaml_file)

            return render_template(
                "sealed_secret.html", sealed_secret=sealed_secret_yaml, download_file=sealed_yaml_path
            )

        except subprocess.CalledProcessError as e:
            return f"❌ Error: {str(e)}", 500

    return render_template("index.html", namespaces=namespaces, error_message="")

@app.route("/download/<filename>")
def download_file(filename):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    return send_file(file_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
