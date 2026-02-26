"""
Video Personalization Server - R2 Cloud Storage Support
Handles QR code replacement in merchant videos with cloud-stored templates
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import qrcode
import cv2
import numpy as np
from PIL import Image
import io
import os
import tempfile
import uuid
from datetime import datetime
import json
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)
CORS(app)

# Configuration
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/generated_videos')
QR_SIZE = int(os.getenv('QR_SIZE', 400))

# R2 Configuration
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'cherry-videos')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', 'https://pub-45ce7f94115b43188d5b1432ac8d59c9.r2.dev')

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Initialize R2 client (S3-compatible)
s3_client = None
if R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY:
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name='auto'
        )
        app.logger.info("R2 storage client initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize R2 client: {e}")

# Video Template Library - R2 paths
VIDEO_TEMPLATES = {
    "medspa_aesthetics": {
        "name": "MedSpa/Aesthetics",
        "r2_key": "templates/30_sec_Patient-Facing_Cherry_Video_for_MedSpa_Practices.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 912,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second patient-facing video for MedSpa practices"
    },
    "medspa_vertical": {
        "name": "MedSpa/Aesthetics (Vertical)",
        "r2_key": "templates/Vertical-Neutral_Patient_Facing_Video.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2661,
        "fps": 30,
        "duration": 88.7,
        "description": "Vertical format patient-facing video for MedSpa"
    },
    "dental_30sec": {
        "name": "Dental (30 sec)",
        "r2_key": "templates/30_sec_Patient-Facing_Cherry_Video_for_Dental_Practices.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 912,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second patient-facing video for Dental practices"
    },
    "dental_full": {
        "name": "Dental (Full Length)",
        "r2_key": "templates/Patient-Facing_Cherry_Video_for_Dental_Practices.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2583,
        "fps": 30,
        "duration": 86.1,
        "description": "Full-length patient-facing video for Dental practices"
    },
    "plastic_surgery_30sec": {
        "name": "Plastic Surgery (30 sec)",
        "r2_key": "templates/30_sec_Patient-Facing_Cherry_Video_for_Plastic_Surgery_Practices_1_.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 913,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second patient-facing video for Plastic Surgery practices"
    },
    "plastic_surgery_full": {
        "name": "Plastic Surgery (Full Length)",
        "r2_key": "templates/Patient-Facing_Cherry_Video_for_Plastic_Surgery_Practices_2_.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2583,
        "fps": 30,
        "duration": 86.1,
        "description": "Full-length patient-facing video for Plastic Surgery practices"
    },
    "vet_30sec": {
        "name": "Veterinary (30 sec)",
        "r2_key": "templates/_Short Vet Video.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 912,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second patient-facing video for Veterinary practices"
    },
    "vet_89s": {
        "name": "Veterinary (89 sec)",
        "r2_key": "templates/Vet Video (1).mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2670,
        "fps": 30,
        "duration": 88.7,
        "description": "Full-length patient-facing video for Veterinary practices"
    },
    "medspa_aesthetics_neutral": {
        "name": "MedSpa Neutral (30 sec)",
        "r2_key": "templates/Neutral MedSpa Short Practices (1).mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 912,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second neutral theme video for MedSpa practices"
    },
    "medspa_vertical_neutral": {
        "name": "MedSpa/Plastics Neutral (Full)",
        "r2_key": "templates/MedSpa_Plastics Neutral.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2661,
        "fps": 30,
        "duration": 88.7,
        "description": "Full-length neutral theme for MedSpa and Plastics"
    },
    "plastic_surgery_30sec_neutral": {
        "name": "Plastics Neutral (30 sec)",
        "r2_key": "templates/Short Plastic Surgery Practices.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 912,
        "fps": 30,
        "duration": 30.4,
        "description": "30-second neutral theme video for Plastics practices"
    },
    "plastic_surgery_full_neutral": {
        "name": "Plastics Neutral (Full)",
        "r2_key": "templates/MedSpa_Plastics Neutral.mp4",
        "qr_start_frame": 0,
        "qr_duration_frames": 2661,
        "fps": 30,
        "duration": 88.7,
        "description": "Full-length neutral theme for Plastics practices"
    },
}


def download_from_r2(r2_key, local_path):
    """Download a file from R2 to local temp storage"""
    if not s3_client:
        raise Exception("R2 client not initialized. Check environment variables.")
    
    try:
        app.logger.info(f"Downloading {r2_key} from R2...")
        s3_client.download_file(R2_BUCKET_NAME, r2_key, local_path)
        app.logger.info(f"Successfully downloaded {r2_key}")
        return True
    except ClientError as e:
        app.logger.error(f"Error downloading from R2: {e}")
        raise Exception(f"Failed to download template from R2: {str(e)}")


def upload_to_r2(local_path, r2_key):
    """Upload a file from local storage to R2"""
    if not s3_client:
        raise Exception("R2 client not initialized. Check environment variables.")
    
    try:
        app.logger.info(f"Uploading {r2_key} to R2...")
        s3_client.upload_file(local_path, R2_BUCKET_NAME, r2_key)
        app.logger.info(f"Successfully uploaded {r2_key}")
        
        url = f"{R2_PUBLIC_URL}/{r2_key}"
        return url
    except ClientError as e:
        app.logger.error(f"Error uploading to R2: {e}")
        raise Exception(f"Failed to upload to R2: {str(e)}")


def check_r2_file_exists(r2_key):
    """Check if a file exists in R2"""
    if not s3_client:
        return False
    
    try:
        s3_client.head_object(Bucket=R2_BUCKET_NAME, Key=r2_key)
        return True
    except ClientError:
        return False


def append_utm_params(url, practice_type='unknown', organization_id='unknown'):
    """
    Append UTM tracking parameters to the application URL for attribution.
    Preserves any existing query parameters.
    """
    parsed = urlparse(url)
    existing_params = parse_qs(parsed.query)

    utm_params = {
        'utm_source': 'cherry_video_generator',
        'utm_medium': 'qr_code_cherry_video_generator',
        'utm_campaign': f'waiting_room_{practice_type}',
        'utm_content': organization_id
    }

    for key, value in utm_params.items():
        if key not in existing_params:
            existing_params[key] = [value]

    new_query = urlencode(existing_params, doseq=True)
    new_url = urlunparse(parsed._replace(query=new_query))
    return new_url


def generate_qr_with_branding(url, size=400):
    """Generate QR code with Cherry branding"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img = qr_img.convert('RGB')
    qr_img = qr_img.resize((size, size), Image.Resampling.LANCZOS)
    
    qr_array = np.array(qr_img)
    return qr_array


def add_qr_to_video(template_path, output_path, qr_code_url, template_info, floating=False):
    """Add QR code with Cherry branding to video"""
    qr_array = generate_qr_with_branding(qr_code_url, QR_SIZE)
    
    cap = cv2.VideoCapture(template_path)
    if not cap.isOpened():
        raise Exception(f"Could not open template video: {template_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    qr_display_size = int(min(width, height) * 0.18)
    qr_resized = cv2.resize(qr_array, (qr_display_size, qr_display_size))
    
    container_padding = 12
    container_width = qr_display_size + (container_padding * 2)
    container_height = qr_display_size + 70
    
    margin = 15
    base_container_x = width - container_width - margin
    base_container_y = (height - container_height) // 2
    
    frame_count = 0
    start_frame = template_info.get('qr_start_frame', 0)
    duration_frames = template_info.get('qr_duration_frames', total_frames)
    
    app.logger.info(f"Processing video: {total_frames} frames, QR mode: {'FLOATING' if floating else 'STATIC'}")
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        if floating and frame_count >= start_frame and frame_count < (start_frame + duration_frames):
            import math
            progress = (frame_count - start_frame) / float(duration_frames)
            angle = progress * math.pi * 4
            y_range = height - container_height - (margin * 2)
            offset_y = int((math.sin(angle) + 1) * y_range / 2)
            container_x = base_container_x
            container_y = margin + offset_y
        else:
            container_x = base_container_x
            container_y = base_container_y
        
        if frame_count >= start_frame and frame_count < (start_frame + duration_frames):
            overlay = frame.copy()
            
            cv2.rectangle(overlay,
                         (container_x, container_y),
                         (container_x + container_width, container_y + container_height),
                         (255, 255, 255), -1)
            
            wood_color = (102, 153, 204)
            border_thickness = 8
            
            cv2.rectangle(overlay,
                         (container_x, container_y),
                         (container_x + container_width, container_y + container_height),
                         wood_color, border_thickness)
            
            text = "Apply Now"
            text_font = cv2.FONT_HERSHEY_SIMPLEX
            text_scale = 0.9
            text_thickness = 3
            (text_width, text_height), _ = cv2.getTextSize(text, text_font, text_scale, text_thickness)
            text_x = container_x + (container_width - text_width) // 2
            text_y = container_y + 40
            
            cv2.putText(overlay, text,
                       (text_x, text_y),
                       text_font, text_scale, (30, 30, 30),
                       text_thickness, cv2.LINE_AA)
            
            qr_x = container_x + (container_width - qr_display_size) // 2
            qr_y = container_y + 58
            overlay[qr_y:qr_y + qr_display_size,
                   qr_x:qr_x + qr_display_size] = qr_resized
            
            alpha = 0.95
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
        
        out.write(frame)
        frame_count += 1
    
    cap.release()
    out.release()
    
    return {
        'total_frames': total_frames,
        'fps': fps,
        'video_duration_seconds': total_frames / fps,
        'qr_position': 'bottom-right',
        'qr_persistent': True
    }


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    templates_status = {}
    for key, template in VIDEO_TEMPLATES.items():
        templates_status[key] = check_r2_file_exists(template['r2_key'])
    
    return jsonify({
        'status': 'healthy',
        'templates_available': templates_status,
        'r2_configured': s3_client is not None,
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/api/templates', methods=['GET'])
def list_templates():
    """List all available video templates with R2 availability"""
    templates = []
    for key, template in VIDEO_TEMPLATES.items():
        available = check_r2_file_exists(template['r2_key'])
        templates.append({
            'id': key,
            'name': template['name'],
            'description': template['description'],
            'duration': template['duration'],
            'available': available
        })
    
    return jsonify({
        'templates': templates,
        'count': len(templates)
    })


@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    """Generate personalized video with QR code from R2-stored templates"""
    try:
        data = request.json
        application_url = data.get('application_url')
        practice_type = data.get('practice_type')
        qr_animation = data.get('qr_animation', 'static')
        organization_id = data.get('organization_id', 'unknown')
        organization_name = data.get('organization_name', '')
        
        if not application_url or not practice_type:
            return jsonify({'error': 'Missing required fields'}), 400
        
        if practice_type not in VIDEO_TEMPLATES:
            return jsonify({'error': f'Invalid practice type: {practice_type}'}), 400
        
        template_info = VIDEO_TEMPLATES[practice_type]
        
        if not check_r2_file_exists(template_info['r2_key']):
            return jsonify({
                'error': 'Template not found in R2 storage',
                'template': template_info['name'],
                'r2_key': template_info['r2_key']
            }), 404
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_id = str(uuid.uuid4())[:8]
        
        template_local_path = f"/tmp/template_{video_id}.mp4"
        download_from_r2(template_info['r2_key'], template_local_path)
        
        output_filename = f"cherry_{practice_type}_{organization_id}_{timestamp}_{video_id}.mp4"
        output_local_path = os.path.join(OUTPUT_DIR, output_filename)
        
        app.logger.info(f"Generating video: {output_filename} (QR: {qr_animation})")
        
        tracked_url = append_utm_params(application_url, practice_type, organization_id)
        app.logger.info(f"QR URL with UTM: {tracked_url}")
        
        floating = (qr_animation == 'floating')
        video_info = add_qr_to_video(
            template_local_path,
            output_local_path,
            tracked_url,
            template_info,
            floating=floating
        )
        
        output_r2_key = f"generated/{output_filename}"
        output_url = upload_to_r2(output_local_path, output_r2_key)
        
        try:
            os.remove(template_local_path)
        except:
            pass
        
        file_size_mb = round(os.path.getsize(output_local_path) / (1024 * 1024), 2)
        
        app.logger.info(f"Video generated successfully: {output_filename} ({file_size_mb} MB)")
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'download_url': f'/api/download/{video_id}',
            'r2_url': output_url,
            'filename': output_filename,
            'application_url': application_url,
            'tracked_url': tracked_url,
            'practice_type': practice_type,
            'template_name': template_info['name'],
            'organization_id': organization_id,
            'video_info': video_info,
            'file_size_mb': file_size_mb,
            'created_at': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        app.logger.error(f"Error generating video: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


@app.route('/api/download/<video_id>', methods=['GET'])
def download_video(video_id):
    """Download generated video by video ID"""
    try:
        app.logger.info(f"Download request for video_id: {video_id}")
        
        video_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.mp4') and video_id in f]
        
        app.logger.info(f"Found {len(video_files)} files matching video_id")
        
        if not video_files:
            return jsonify({
                'error': 'Video not found',
                'video_id': video_id
            }), 404
        
        video_filename = video_files[0]
        video_path = os.path.join(OUTPUT_DIR, video_filename)
        
        app.logger.info(f"Serving video: {video_path}")
        
        return send_file(
            video_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'cherry_personalized_{video_id}.mp4'
        )
    
    except Exception as e:
        app.logger.error(f"Error downloading video: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
