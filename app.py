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

FEAST_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" fill="none">
  <rect width="128" height="128" rx="28" fill="#F7F3EE"/>
  <g transform="translate(0, 34)">
    <path d="M4 13H24.5V19.8H11.8V28.4H22.2V35.2H11.8V49H4V13Z" fill="#C84B31"/>
    <path d="M39 22.4C46.5 22.4 51.2 27.8 51.2 35.8V38.2H33.4C34.1 42.1 36.8 44.3 40.8 44.3C43.8 44.3 45.8 43 47.2 41.3L51.5 45.4C49 48.5 45.2 50.4 40.1 50.4C31.6 50.4 26 44.7 26 36.4C26 28 31.6 22.4 39 22.4ZM33.5 33.4H43.9C43.4 30 41.5 28.2 38.8 28.2C36 28.2 34.1 30.1 33.5 33.4Z" fill="#C84B31"/>
    <path d="M65.2 22.4C72.7 22.4 77.2 26.4 77.2 33.4V49H70V45.9C68.3 48.3 65.5 49.7 62.1 49.7C56.9 49.7 53.5 46.4 53.5 41.6C53.5 36.4 57.5 33.6 64.3 33L69.8 32.5V31.6C69.8 28.8 67.9 27.2 64.9 27.2C62.1 27.2 60.3 28.4 59.4 30.3L53.9 27.6C55.8 23.8 59.8 22.4 65.2 22.4ZM69.8 37.3L65.2 37.7C62.1 38 60.6 39.3 60.6 41.3C60.6 43.3 62.2 44.5 64.5 44.5C67.7 44.5 69.8 42.4 69.8 39.3V37.3Z" fill="#C84B31"/>
    <path d="M90.5 22.4C95.8 22.4 99.6 24.7 101.1 28.4L95.5 30.8C94.6 28.8 92.9 27.8 90.5 27.8C88.3 27.8 86.9 28.7 86.9 30.2C86.9 31.6 88.2 32.4 91.2 33.1L94.4 33.8C99.5 35 102 37.7 102 42.1C102 47.4 97.3 50.4 90.4 50.4C84.4 50.4 80.2 47.8 78.8 43.8L84.6 41.3C85.6 43.7 87.6 45 90.6 45C93.1 45 94.6 44 94.6 42.4C94.6 40.9 93.4 40.1 90.4 39.4L87.1 38.7C82.3 37.6 79.7 34.9 79.7 30.6C79.7 25.5 84.1 22.4 90.5 22.4Z" fill="#C84B31"/>
    <path d="M107.2 15.8H114.6V23H119.8V28.9H114.6V40.4C114.6 43.1 115.8 44.3 118.4 44.3H120V49.8H117C110.6 49.8 107.2 46.8 107.2 40.6V28.9H103.6V23H107.2V15.8Z" fill="#C84B31"/>
    <path d="M111.1 14.8C109.9 8.2 115.4 2.7 123.3 1.7C122.9 9.7 117.8 15.1 111.1 14.8Z" fill="#1D8A5A"/>
    <path d="M111.8 14.1C114.9 10.6 118.3 7.3 122.1 3.1" stroke="#F7F3EE" stroke-width="1.55" stroke-linecap="round"/>
  </g>
</svg>
"""


@app.route('/')
def index():
    """Serves the Feast campus dining companion webpage."""
    return render_template('index.html')


@app.route('/favicon.svg')
def favicon_svg():
    """Serves the updated geometric Feast SVG favicon directly so sanitizers never strip it."""
    resp = Response(FEAST_FAVICON_SVG, mimetype='image/svg+xml')
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    """Serves the web app manifest pointing to the geometric Feast SVG icon."""
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
                'src': '/favicon.svg?v=2',
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