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

# Brand logo SVG based on uploaded brand wordmark
FEAST_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="50 15 840 390" fill="none">
  <path d="M 76.0 140.9 L 220.0 140.5 L 222.7 141.0 L 224.2 143.0 L 224.5 192.0 L 223.1 195.0 L 150.0 195.5 L 146.9 197.0 L 147.0 239.6 L 150.0 240.5 L 215.2 241.0 L 217.4 244.0 L 217.5 285.0 L 216.1 294.0 L 213.0 296.4 L 150.0 296.5 L 147.0 297.4 L 146.5 379.0 L 145.4 382.0 L 143.0 383.4 L 78.0 383.5 L 75.9 383.0 L 74.6 381.0 L 72.5 352.0 L 72.5 320.0 L 74.5 292.0 L 74.5 242.0 L 72.5 225.0 L 74.5 204.0 L 74.5 180.0 L 72.6 173.0 L 72.5 157.0 L 74.6 143.0 L 76.0 140.9 Z" fill="#C84B31"/>
  <path d="M 301.0 205.8 L 338.0 205.6 L 361.0 211.7 L 371.0 218.6 L 379.4 227.0 L 385.2 235.0 L 392.3 249.0 L 397.2 265.0 L 399.5 278.0 L 399.5 309.0 L 397.1 316.0 L 380.0 317.5 L 360.0 316.5 L 301.0 316.5 L 299.4 317.0 L 298.6 319.0 L 300.5 322.0 L 306.0 326.4 L 318.0 334.3 L 338.0 338.4 L 350.0 338.4 L 369.0 335.2 L 382.0 330.6 L 385.1 331.0 L 386.5 334.0 L 386.5 374.0 L 386.0 376.1 L 384.0 377.7 L 364.0 383.4 L 353.0 385.4 L 336.0 386.5 L 301.0 385.4 L 291.0 383.2 L 274.0 377.3 L 263.0 371.2 L 257.0 366.4 L 244.0 353.3 L 233.7 335.0 L 230.8 327.0 L 227.6 311.0 L 226.9 294.0 L 231.8 268.0 L 239.3 251.0 L 251.6 233.0 L 260.0 224.6 L 268.0 218.6 L 282.0 210.8 L 301.0 205.8 Z M 318.0 247.8 L 312.8 249.0 L 305.8 256.0 L 300.8 268.0 L 300.0 276.1 L 303.0 277.5 L 338.1 277.0 L 339.4 275.0 L 339.4 271.0 L 334.2 255.0 L 328.0 249.3 L 322.0 247.6 L 318.0 247.8 Z" fill="#C84B31" fill-rule="evenodd"/>
  <path d="M 481.0 204.8 L 513.0 205.6 L 534.0 211.3 L 548.0 219.8 L 553.0 224.8 L 564.3 243.0 L 569.4 261.0 L 573.5 293.0 L 571.5 323.0 L 572.5 379.0 L 570.0 383.1 L 555.0 383.5 L 540.0 381.5 L 509.0 383.4 L 506.6 381.0 L 505.4 364.0 L 503.0 360.2 L 490.0 374.4 L 476.0 383.1 L 469.0 385.4 L 457.0 386.5 L 439.0 385.4 L 430.0 382.7 L 416.0 374.4 L 409.8 367.0 L 405.7 359.0 L 400.7 337.0 L 401.6 324.0 L 405.9 307.0 L 411.0 297.7 L 419.5 289.0 L 426.0 283.8 L 442.0 275.8 L 460.0 271.6 L 492.0 269.4 L 504.0 267.3 L 505.2 266.0 L 502.4 261.0 L 496.0 254.5 L 487.0 250.8 L 479.0 249.5 L 451.0 253.8 L 419.0 264.1 L 416.5 259.0 L 416.5 242.0 L 418.3 220.0 L 420.0 217.9 L 439.0 210.8 L 466.0 205.6 L 481.0 204.8 Z M 501.0 301.8 L 482.0 304.8 L 471.0 309.5 L 466.9 315.0 L 465.5 320.0 L 465.6 328.0 L 469.0 334.4 L 481.0 338.5 L 494.0 333.9 L 498.2 329.0 L 501.2 323.0 L 506.4 306.0 L 505.1 302.0 L 501.0 301.8 Z" fill="#C84B31" fill-rule="evenodd"/>
  <path d="M 663.0 203.8 L 674.0 203.5 L 689.0 205.6 L 713.0 210.6 L 716.1 213.0 L 715.5 246.0 L 714.4 256.0 L 713.1 258.0 L 711.0 258.4 L 699.0 254.6 L 672.0 249.5 L 664.0 250.8 L 658.0 253.8 L 655.9 256.0 L 655.5 259.0 L 658.0 264.2 L 691.0 277.9 L 711.0 289.8 L 717.0 295.7 L 722.1 305.0 L 726.5 322.0 L 726.4 331.0 L 721.1 350.0 L 715.0 359.5 L 701.0 372.2 L 691.0 378.2 L 669.0 385.4 L 654.0 386.5 L 620.0 385.4 L 588.0 379.2 L 586.0 377.7 L 585.5 375.0 L 585.5 333.0 L 587.8 329.0 L 591.0 328.8 L 608.0 335.2 L 629.0 339.5 L 646.0 339.2 L 656.0 335.7 L 659.4 332.0 L 657.0 326.5 L 648.0 320.3 L 626.0 313.2 L 609.0 305.2 L 597.5 296.0 L 592.0 289.3 L 587.8 281.0 L 584.5 269.0 L 584.6 259.0 L 590.8 239.0 L 598.0 227.7 L 604.5 221.0 L 619.0 211.9 L 641.0 205.6 L 663.0 203.8 Z" fill="#C84B31"/>
  <path d="M 817.0 173.8 L 820.0 174.3 L 821.3 176.0 L 822.5 206.0 L 823.9 209.0 L 855.0 209.6 L 858.4 213.0 L 858.1 256.0 L 854.0 259.4 L 825.0 259.5 L 822.0 260.9 L 821.5 304.0 L 823.8 322.0 L 825.9 328.0 L 828.0 330.4 L 834.0 333.4 L 841.0 333.4 L 854.0 330.6 L 858.1 333.0 L 858.5 374.0 L 856.0 380.7 L 847.0 383.2 L 836.0 385.4 L 808.0 386.5 L 796.0 385.4 L 787.0 383.2 L 775.0 377.2 L 764.0 367.2 L 758.7 359.0 L 751.8 341.0 L 750.6 333.0 L 749.5 313.0 L 750.5 306.0 L 750.3 261.0 L 746.0 258.6 L 728.0 259.4 L 723.9 257.0 L 723.2 213.0 L 724.0 210.8 L 726.0 209.6 L 750.0 208.7 L 751.3 205.0 L 750.5 183.0 L 752.0 179.9 L 787.0 178.4 L 804.0 175.6 L 813.0 175.4 L 817.0 173.8 Z" fill="#C84B31"/>
  <path d="M 859.0 31.8 L 866.0 31.6 L 868.4 34.0 L 867.5 61.0 L 864.4 86.0 L 857.1 109.0 L 847.2 126.0 L 840.4 134.0 L 828.3 144.0 L 815.0 152.1 L 793.0 159.2 L 773.0 161.5 L 761.0 161.4 L 757.9 159.0 L 757.0 154.4 L 754.0 153.5 L 748.0 153.7 L 744.0 158.9 L 742.0 158.1 L 740.6 153.0 L 739.5 135.0 L 743.8 107.0 L 752.7 84.0 L 763.0 69.5 L 773.0 59.6 L 783.0 52.5 L 800.0 43.8 L 811.0 39.8 L 831.0 35.6 L 859.0 31.8 Z" fill="#1D8A5A"/>
  <path d="M 755 150 Q 782 118 827 78" stroke="#000000" stroke-width="6" stroke-linecap="round"/>
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
                'src': '/favicon.svg?v=4',
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
    """Allows the creator to view submitted feedback entries with admin authorization."""
    admin_key = os.environ.get('ADMIN_KEY') or os.environ.get('FEEDBACK_ADMIN_KEY')
    provided_key = request.headers.get('X-Admin-Key') or request.args.get('key')

    if not admin_key or provided_key != admin_key:
        return jsonify({'error': 'Unauthorized access.'}), 401

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