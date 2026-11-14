import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests as rq
from flask import Flask, Response, render_template, request, jsonify
from purdue_menus_full_analysis import recommend_meals, _parse_user_time_input

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
FEEDBACK_FILE = os.path.join(BASE_DIR, 'feast_feedback.json')
PURDUE_TZ = ZoneInfo("America/Indiana/Indianapolis")

# Brand logo SVG based on image_2.png
FEAST_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 84" fill="none">
  <path d="M15.4 28H39.4V36.2H23.9V46.6H36.3V54.7H23.9V71.3H15.4V28Z" fill="#C84B31"/>
  <path d="M54.1 39.4C63.1 39.4 68.7 45.9 68.7 55.4V58.3H47.4C48.2 63.1 51.5 65.7 56.3 65.7C59.9 65.7 62.3 64.2 64.0 62.1L69.1 67C66.1 70.8 61.6 73.1 55.5 73.1C45.3 73.1 38.6 66.2 38.6 56.3C38.6 46.2 45.3 39.4 54.1 39.4ZM47.6 52.6H59.9C59.3 48.6 57.0 46.4 53.8 46.4C50.5 46.4 48.2 48.7 47.6 52.6Z" fill="#C84B31"/>
  <path d="M85.4 39.4C94.4 39.4 99.8 44.2 99.8 52.6V71.3H91.1V67.6C89.1 70.5 85.8 72.2 81.7 72.2C75.5 72.2 71.4 68.2 71.4 62.5C71.4 56.2 76.2 52.9 84.3 52.2L91.0 51.6V50.5C91.0 47.1 88.7 45.2 85.1 45.2C81.7 45.2 79.5 46.6 78.5 48.9L71.9 45.7C74.1 41.1 79.0 39.4 85.4 39.4ZM91.0 57.3L85.4 57.8C81.7 58.2 79.9 59.7 79.9 62.1C79.9 64.5 81.8 66 84.6 66C88.5 66 91.0 63.4 91.0 59.7V57.3Z" fill="#C84B31"/>
  <path d="M115.8 39.4C122.1 39.4 126.7 42.1 128.5 46.6L121.8 49.5C120.7 47.1 118.7 45.9 115.8 45.9C113.2 45.9 111.5 47 111.5 48.8C111.5 50.5 113.1 51.4 116.7 52.3L120.5 53.1C126.6 54.6 129.6 57.8 129.6 63.1C129.6 69.5 124.0 73.1 115.7 73.1C108.5 73.1 103.5 69.9 101.8 65.1L108.8 62.1C110.0 65 112.4 66.6 115.9 66.6C118.9 66.6 120.7 65.4 120.7 63.5C120.7 61.7 119.3 60.7 115.7 59.9L111.7 59.1C106.0 57.8 102.9 54.5 102.9 49.3C102.9 43.1 108.2 39.4 115.8 39.4Z" fill="#C84B31"/>
  <path d="M135.8 31.4H144.7V40.1H150.9V47.2H144.7V61.0C144.7 64.2 146.1 65.7 149.2 65.7H151.2V72.3H147.6C140.0 72.3 135.8 68.7 135.8 61.3V47.2H131.5V40.1H135.8V31.4Z" fill="#C84B31"/>
  <path d="M133.5 31.5C132.5 19.3 140.6 8.5 151.1 5.3C152.0 17.5 144.5 28.5 133.5 31.5Z" fill="#1D8A5A"/>
  <path d="M134.3 30.6C141.0 23.3 145.4 15.6 148.9 7.3" stroke="#F7F3EE" stroke-width="1.6" stroke-linecap="round"/>
</svg>
"""


@app.route('/')
def index():
    """Serves the Feast campus dining companion webpage."""
    return render_template('index.html')


@app.route('/favicon.svg')
def favicon_svg():
    """Serves the brand Feast SVG favicon directly to prevent caching and parsing issues."""
    resp = Response(FEAST_FAVICON_SVG, mimetype='image/svg+xml')
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    """Serves the web app manifest pointing to the brand Feast SVG icon."""
    manifest = {
        'name': 'Feast — Purdue Campus Dining',
        'short_name': 'Feast',
        'description': 'Fast, clean campus dining meal recommendations at Purdue University.',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#F7F3EE',
        'theme_color': '#F7F3EE',
        'icons': [
            {
                'src': '/favicon.svg?v=3',
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any maskable',
            }
        ],
    }
    resp = Response(
        json.dumps(manifest),
        mimetype='application/manifest+json',
    )
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    """Receives mode, allergy/dietary filters, Pure Health toggle, and optional DRI biometrics as JSON."""
    data = request.get_json(silent=True) or {}

    try:
        pure_health_mode = bool(data.get('pure_health_mode', False))
        raw_intensity = str(data.get('health_intensity', 'High')).strip() or 'High'
        health_intensity = 'Extreme' if pure_health_mode else raw_intensity

        dri_enabled = bool(data.get('dri_enabled', False))
        meal_goal = str(data.get('meal_goal', 'Balanced Maintenance')).strip() or 'Balanced Maintenance'

        raw_filters = data.get('dietary_filters') or []
        dietary_filters = [str(f).strip().lower() for f in raw_filters if str(f).strip()]

        sim_raw = str(data.get('sim_time', '')).strip()
        sim_time = _parse_user_time_input(sim_raw) if sim_raw else None

        sex = None
        age = None
        weight_lbs = None
        height_in = None
        activity_level = None
        meals_per_day = None

        if dri_enabled:
            sex = str(data.get('sex') or '').strip()
            age_raw = data.get('age')
            weight_raw = data.get('weight_lbs')
            height_raw = data.get('height_in')
            activity_level = str(data.get('activity_level') or '').strip()
            meals_raw = data.get('meals_per_day')

            if not all([
                sex,
                age_raw not in (None, ''),
                weight_raw not in (None, ''),
                height_raw not in (None, ''),
                activity_level,
                meals_raw not in (None, ''),
            ]):
                return jsonify({
                    'error': 'Please complete all body & target fields (Sex, Age, Weight, Height, Activity, and Meals/Day) to personalize portions.'
                }), 400

            age = int(age_raw)
            weight_lbs = float(weight_raw)
            height_in = float(height_raw)
            meals_per_day = int(meals_raw)

            if age <= 0 or weight_lbs <= 0 or height_in <= 0 or meals_per_day <= 0:
                return jsonify({'error': 'Biometric values must be positive numbers.'}), 400

        result = recommend_meals(
            sex=sex,
            age=age,
            weight_lbs=weight_lbs,
            height_in=height_in,
            activity_level=activity_level,
            meals_per_day=meals_per_day,
            meal_goal=meal_goal,
            health_intensity=health_intensity,
            dri_enabled=dri_enabled,
            dietary_filters=dietary_filters,
            current_time=sim_time,
        )
        return jsonify(result)

    except ValueError as val_err:
        return jsonify({'error': str(val_err)}), 400
    except Exception as exc:
        return jsonify({'error': f'Unexpected error: {exc}'}), 500


@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    """Stores student feedback, dish requests, and bug reports locally and optionally forwards via webhook."""
    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    category = str(data.get('category') or 'General').strip()
    contact = str(data.get('contact') or '').strip()

    if not message:
        return jsonify({'error': 'Please write a quick note before sending.'}), 400

    entry = {
        'timestamp': datetime.now(PURDUE_TZ).strftime('%Y-%m-%d %I:%M %p %Z'),
        'category': category[:60],
        'message': message[:1500],
        'contact': contact[:120],
    }

    try:
        existing = []
        if os.path.exists(FEEDBACK_FILE):
            with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    existing = loaded
        existing.append(entry)
        with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    except OSError:
        pass

    webhook_url = os.environ.get('FEEDBACK_WEBHOOK_URL', '').strip()
    if webhook_url:
        try:
            webhook_payload = {
                'app': 'Feast Purdue Dining',
                'content': (
                    f"**Feast Feedback ({entry['category']})**\n"
                    f"{entry['message']}\n"
                    f"_Contact:_ {entry['contact'] or 'Anonymous'} | _{entry['timestamp']}_"
                ),
                **entry,
            }
            rq.post(webhook_url, json=webhook_payload, timeout=5)
        except rq.exceptions.RequestException:
            pass

    print(f"[FEAST FEEDBACK] {entry['timestamp']} | {entry['category']} | {entry['message']} ({entry['contact']})", flush=True)
    return jsonify({'ok': True, 'message': 'Thanks for helping shape Feast!'})


@app.route('/api/feedback', methods=['GET'])
def api_get_feedback():
    """Allows the creator to view submitted feedback entries."""
    if not os.path.exists(FEEDBACK_FILE):
        return jsonify({'count': 0, 'entries': []})
    try:
        with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        return jsonify({'count': len(entries), 'entries': list(reversed(entries))})
    except (OSError, ValueError):
        return jsonify({'count': 0, 'entries': []})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)