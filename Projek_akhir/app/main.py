from flask import Flask, request, render_template, redirect, flash, Response, jsonify
import os
import random
import shutil
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import logging
from functools import wraps

UPLOAD_FOLDER = '/app/uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB (sesuai dengan docker-compose)

# Inisialisasi Flask
app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cek dan buat folder upload
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Fungsi validasi file
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Metrik Prometheus
error_500_counter = Counter('app_error_500_total', 'Total number of 500 errors')
disk_usage_gauge = Gauge('disk_usage_percent', 'Disk usage in percent')
upload_total = Counter('upload_total', 'Total number of uploads')
upload_failed = Counter('upload_failed', 'Number of failed uploads')
http_requests = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])

def monitor_request(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            response = f(*args, **kwargs)
            status = response[1] if isinstance(response, tuple) else 200
            http_requests.labels(
                method=request.method,
                endpoint=request.path,
                status=status
            ).inc()
            return response
        except Exception as e:
            http_requests.labels(
                method=request.method,
                endpoint=request.path,
                status=500
            ).inc()
            raise e
    return decorated_function

def get_disk_usage_percent():
    try:
        # Target max size 150MB (sedikit di atas MAX_UPLOAD_SIZE untuk buffer)
        target_max_size = 150 * 1024 * 1024
        total_size = 0

        # Pastikan direktori ada
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
            logger.info("Created upload directory")
            return 0

        # Hitung total ukuran file dalam folder uploads
        for path, dirs, files in os.walk(UPLOAD_FOLDER):
            for f in files:
                fp = os.path.join(path, f)
                if os.path.isfile(fp):  # Pastikan ini adalah file
                    total_size += os.path.getsize(fp)

        usage = (total_size / target_max_size) * 100
        logger.info(f"Upload folder size: {total_size/(1024*1024):.2f}MB, Usage: {usage:.2f}% of {target_max_size/(1024*1024)}MB limit")
        
        # Tambahkan warning jika usage sudah tinggi
        if usage > 70:
            logger.warning(f"High storage usage warning: {usage:.2f}%")
        
        return usage
    except Exception as e:
        logger.error(f"Error checking upload folder size: {str(e)}")
        return 0

# ROUTES
@app.route('/')
@monitor_request
def upload_form():
    return render_template('upload.html')

@app.route('/', methods=['POST'])
@monitor_request
def upload_file():
    try:
        if 'file' not in request.files:
            flash('No file part')
            upload_failed.inc()
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected')
            upload_failed.inc()
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash('File type not allowed')
            upload_failed.inc()
            return redirect(request.url)

        # Check disk space before upload
        if get_disk_usage_percent() > 80:
            flash('Upload failed: Disk space is running low')
            upload_failed.inc()
            return redirect(request.url)

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        upload_total.inc()
        flash('File successfully uploaded')
        return redirect('/')

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        upload_failed.inc()
        error_500_counter.inc()
        return "Internal Server Error", 500

@app.route('/metrics')
def metrics():
    try:
        usage = get_disk_usage_percent()
        disk_usage_gauge.set(usage)
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
    except Exception as e:
        logger.error(f"Metrics error: {str(e)}")
        return "Metrics collection failed", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        alert = request.json
        logger.info(f"Alert received: {alert}")
        # Handle different alert types
        if alert.get('status') == 'firing':
            for alert in alert.get('alerts', []):
                if alert.get('labels', {}).get('alertname') == 'HighDiskUsage':
                    logger.warning("High disk usage alert received!")
                elif alert.get('labels', {}).get('alertname') == 'High500ErrorRate':
                    logger.error("High error rate alert received!")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    upload_failed.inc()
    flash('File too large')
    return redirect('/')

@app.route('/test500')
def test_500():
    """Endpoint untuk testing error 500"""
    error_500_counter.inc()
    logger.error('Test 500 error triggered')
    # Tambahkan label status 500 secara eksplisit
    http_requests.labels(
        method=request.method,
        endpoint=request.path,
        status=500
    ).inc()
    return "Internal Server Error", 500

@app.errorhandler(500)
def internal_error(error):
    error_500_counter.inc()
    logger.error(f'500 Error occurred: {str(error)}')
    return "Internal Server Error", 500

# Jalankan Flask
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
