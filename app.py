import os
import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import requests as rq
from flask import Flask, Response, render_template, request, jsonify, send_from_directory
from purdue_menus_full_analysis import recommend_meals, _parse_user_time_input

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
FEEDBACK_FILE = os.path.join(BASE_DIR, 'feast_feedback.json')
PURDUE_TZ = ZoneInfo("America/Indiana/Indianapolis")


def _prewarm_menus_cache():
    """Warms the daily menu cache in the background upon server boot to eliminate user wait time."""
    try:
        recommend_meals(health_intensity='High')
    except Exception:
        pass


# Launch background cache warming on server boot
threading.Thread(target=_prewarm_menus_cache, daemon=True).start()

# Brand logo 512x512 square icon SVG with #F7F3EE solid background and generous padding (safe zone)
FEAST_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="#F7F3EE"/>
  <g transform="translate(55.45, 165.98) scale(0.43)">
    <path d="M 74.0 140.7 L 218.0 141.0 L 224.1 144.0 L 223.0 194.2 L 152.0 195.5 L 147.0 198.2 L 147.0 239.0 L 215.0 241.4 L 217.2 246.0 L 217.5 282.0 L 216.1 293.0 L 212.0 296.3 L 147.0 298.0 L 147.0 378.0 L 143.0 383.5 L 74.0 383.5 L 74.0 380.0 L 74.0 350.0 L 74.0 290.0 L 74.0 159.0 L 74.0 144.0 L 74.0 140.7 Z" fill="#C84B31"/>
    <path d="M 314.5 205.8 L 331.8 206.1 L 346.0 208.0 L 357.6 211.6 L 362.9 214.3 L 372.4 221.3 L 380.6 230.2 L 387.4 240.8 L 392.8 253.2 L 396.7 267.8 L 398.1 275.2 L 399.5 289.9 L 399.0 307.6 L 397.9 312.6 L 396.3 314.1 L 390.3 316.1 L 377.7 317.0 L 307.8 317.0 L 302.3 317.4 L 300.2 319.6 L 301.1 321.6 L 302.5 323.0 L 312.0 330.0 L 320.8 334.2 L 330.5 336.7 L 339.0 338.0 L 345.5 338.2 L 371.9 334.2 L 378.5 335.5 L 383.1 339.7 L 385.6 346.8 L 386.0 364.8 L 385.2 374.2 L 384.3 375.7 L 377.8 378.9 L 358.2 383.8 L 342.1 385.9 L 327.9 385.7 L 307.5 384.3 L 290.6 382.2 L 284.6 380.9 L 276.1 377.6 L 267.6 373.1 L 259.4 367.5 L 252.1 361.3 L 245.8 354.4 L 240.3 346.6 L 233.6 332.4 L 230.2 320.4 L 228.1 309.2 L 227.4 299.8 L 228.1 289.6 L 230.0 278.0 L 232.8 267.1 L 236.5 257.8 L 244.0 244.2 L 250.3 235.6 L 257.1 228.2 L 267.9 219.3 L 275.4 214.7 L 283.8 210.9 L 293.5 208.0 L 299.5 206.9 L 314.5 205.8 Z M 315.8 248.6 L 312.8 249.9 L 309.8 252.2 L 305.4 258.1 L 301.0 269.5 L 300.7 273.4 L 301.8 275.8 L 304.0 276.9 L 310.9 277.4 L 329.0 277.4 L 336.5 276.7 L 338.4 273.9 L 338.5 270.2 L 335.5 260.0 L 332.5 254.1 L 329.4 250.9 L 325.7 249.1 L 321.4 248.3 L 315.8 248.6 Z" fill="#C84B31" fill-rule="evenodd"/>
    <path d="M 492.6 205.2 L 507.6 205.9 L 520.6 207.9 L 526.4 209.5 L 536.8 213.7 L 545.6 219.4 L 553.2 226.7 L 559.5 235.6 L 564.2 244.7 L 567.2 253.5 L 569.5 264.9 L 571.7 280.0 L 572.4 291.4 L 572.7 345.8 L 572.0 373.5 L 571.5 379.7 L 570.9 380.9 L 558.9 382.4 L 547.5 382.8 L 521.0 382.9 L 508.7 382.0 L 507.1 379.7 L 506.5 377.4 L 505.4 367.6 L 503.9 363.0 L 500.5 364.5 L 486.9 376.0 L 474.9 382.6 L 466.2 385.0 L 461.8 385.6 L 453.3 386.1 L 445.6 385.8 L 431.8 381.8 L 421.5 376.7 L 414.0 370.6 L 411.3 367.2 L 406.9 359.5 L 403.8 350.8 L 402.1 341.4 L 401.7 331.5 L 403.2 318.0 L 405.4 310.1 L 409.0 302.8 L 413.6 296.0 L 418.8 290.3 L 424.8 285.4 L 431.6 281.1 L 443.6 275.9 L 458.8 272.4 L 496.8 267.9 L 500.3 267.0 L 501.9 266.2 L 502.5 265.0 L 501.1 261.1 L 496.4 256.3 L 489.2 252.7 L 479.6 250.8 L 473.9 250.7 L 460.5 252.4 L 424.7 261.1 L 420.5 261.3 L 418.1 260.5 L 417.1 255.2 L 417.1 242.9 L 418.0 227.4 L 419.2 219.8 L 421.5 217.9 L 431.0 213.8 L 444.2 210.6 L 474.7 206.2 L 492.6 205.2 Z M 493.9 303.1 L 484.9 304.7 L 477.9 306.8 L 472.8 309.3 L 469.4 312.1 L 466.7 316.5 L 465.7 322.2 L 466.6 329.5 L 467.9 332.2 L 469.2 333.4 L 476.5 336.7 L 483.6 337.7 L 490.5 335.3 L 495.4 331.5 L 498.4 327.4 L 501.3 321.4 L 504.0 313.4 L 505.7 305.5 L 504.5 303.1 L 502.6 302.3 L 493.9 303.1 Z" fill="#C84B31" fill-rule="evenodd"/>
    <path d="M 673.5 204.7 L 687.1 206.0 L 699.2 207.9 L 709.1 210.2 L 714.9 212.9 L 715.8 219.6 L 715.7 233.4 L 715.0 245.3 L 713.9 252.6 L 710.9 254.4 L 705.5 255.0 L 697.6 254.3 L 678.9 251.2 L 667.4 250.8 L 659.7 253.9 L 658.2 255.2 L 656.7 258.3 L 656.8 259.8 L 658.4 262.9 L 661.7 265.1 L 693.6 280.3 L 706.4 287.7 L 714.2 294.1 L 719.0 299.8 L 721.6 305.2 L 723.8 312.4 L 725.3 321.5 L 725.2 327.0 L 723.0 339.8 L 720.0 350.2 L 718.4 353.9 L 711.8 362.2 L 698.4 373.4 L 689.0 378.5 L 676.1 383.0 L 661.2 384.9 L 628.0 385.0 L 609.0 383.1 L 590.4 378.7 L 587.7 377.3 L 586.8 376.0 L 585.7 367.0 L 585.9 336.5 L 586.2 333.1 L 587.9 330.1 L 589.6 329.4 L 592.8 329.9 L 624.8 337.4 L 638.9 338.7 L 653.9 336.4 L 657.1 334.3 L 658.5 331.4 L 658.0 329.1 L 656.4 326.6 L 651.8 322.8 L 624.0 311.0 L 608.4 303.2 L 602.9 299.4 L 595.3 291.4 L 589.6 281.8 L 586.1 271.5 L 584.7 264.2 L 586.1 255.1 L 590.6 241.5 L 595.7 232.6 L 602.2 224.6 L 609.4 218.2 L 617.6 213.5 L 627.1 209.7 L 643.0 205.9 L 660.4 204.4 L 673.5 204.7 Z" fill="#C84B31"/>
    <path d="M 815.9 174.8 L 819.1 175.0 L 820.4 176.0 L 822.9 196.5 L 825.3 202.5 L 829.4 206.6 L 835.2 208.8 L 855.3 210.6 L 857.0 211.8 L 858.1 214.5 L 857.6 241.6 L 856.2 254.9 L 855.2 257.9 L 847.3 259.3 L 829.8 260.1 L 826.0 260.9 L 823.7 262.1 L 822.2 267.2 L 821.5 280.2 L 821.7 298.1 L 822.7 311.5 L 824.9 323.9 L 826.6 327.8 L 829.7 331.1 L 833.3 332.3 L 850.3 331.5 L 856.2 332.2 L 856.9 335.3 L 857.8 349.1 L 857.3 377.5 L 855.4 380.1 L 853.5 381.2 L 831.4 384.8 L 823.1 385.4 L 806.6 385.0 L 798.4 384.1 L 785.4 381.4 L 780.8 379.8 L 774.1 375.9 L 768.6 371.5 L 764.1 366.2 L 757.1 353.4 L 753.6 344.8 L 751.8 337.9 L 750.8 320.5 L 750.0 275.1 L 748.6 260.8 L 747.6 260.1 L 742.7 259.1 L 730.3 258.5 L 725.7 256.7 L 724.8 255.2 L 723.8 245.7 L 724.0 219.5 L 725.1 211.2 L 731.1 209.6 L 741.2 208.7 L 745.6 206.6 L 748.8 203.0 L 750.6 197.8 L 751.2 191.0 L 755.5 185.5 L 763.5 181.4 L 775.2 178.6 L 815.9 174.8 Z" fill="#C84B31"/>
    <path d="M 858.8 32.6 L 863.3 32.4 L 865.9 33.2 L 866.5 33.9 L 866.8 37.1 L 866.1 61.2 L 865.2 70.9 L 862.5 87.9 L 858.1 102.2 L 851.4 115.9 L 843.1 128.3 L 835.0 137.4 L 826.4 143.9 L 815.6 150.0 L 809.4 152.8 L 795.4 157.2 L 779.4 159.8 L 767.4 160.5 L 761.5 159.3 L 760.2 157.6 L 759.8 155.2 L 761.8 148.0 L 765.7 139.8 L 771.2 131.4 L 782.6 119.9 L 809.1 97.7 L 818.5 89.0 L 819.9 86.9 L 818.1 87.3 L 804.8 95.0 L 793.2 102.4 L 776.0 114.8 L 770.2 119.7 L 762.4 128.6 L 749.6 146.6 L 746.2 150.1 L 743.6 150.5 L 742.1 147.7 L 741.4 141.8 L 741.5 129.2 L 743.4 115.5 L 746.3 103.0 L 749.9 92.5 L 754.4 83.2 L 759.7 75.0 L 766.8 67.0 L 776.0 59.0 L 785.2 52.4 L 793.7 47.6 L 799.2 45.4 L 813.9 40.7 L 831.2 36.4 L 843.8 34.0 L 858.8 32.6 Z" fill="#1D8A5A"/>
  </g>
</svg>
"""


@app.after_request
def add_cache_control(response):
    """Prevent browsers from caching HTML pages so updates appear immediately without stale locks."""
    if request.path == '/' or request.path.endswith('.html'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.route('/')
def index():
    """Serves the Feast campus dining companion webpage."""
    return render_template('index.html')


@app.route('/favicon.svg')
def favicon_svg():
    """Serves the brand Feast 512x512 SVG icon directly to prevent caching and parsing issues."""
    resp = Response(FEAST_FAVICON_SVG, mimetype='image/svg+xml')
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def apple_touch_icon():
    """Serves iOS Safari home-screen icon with brand cream background and generous padding."""
    return send_from_directory(os.path.join(BASE_DIR, 'static'), 'apple-touch-icon.png', mimetype='image/png')


@app.route('/icon-192.png')
def icon_192():
    """Serves 192x192 PWA icon with brand cream background and safe-zone padding."""
    return send_from_directory(os.path.join(BASE_DIR, 'static'), 'icon-192.png', mimetype='image/png')


@app.route('/icon-512.png')
def icon_512():
    """Serves 512x512 high-res PWA icon with brand cream background and safe-zone padding."""
    return send_from_directory(os.path.join(BASE_DIR, 'static'), 'icon-512.png', mimetype='image/png')


@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    """Serves the web app manifest pointing to properly padded brand Feast icons on cream background."""
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
                'src': '/apple-touch-icon.png?v=6',
                'sizes': '180x180',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': '/icon-192.png?v=6',
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any maskable',
            },
            {
                'src': '/icon-512.png?v=6',
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any maskable',
            },
            {
                'src': '/favicon.svg?v=6',
                'sizes': '512x512',
                'type': 'image/svg+xml',
                'purpose': 'any maskable',
            },
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


DEFAULT_ADMIN_KEY = 'feast'


@app.route('/feedback')
def feedback_dashboard():
    """Serves the Feast creator feedback dashboard."""
    return render_template('feedback.html')


@app.route('/api/feedback', methods=['GET'])
def api_get_feedback():
    """Allows the creator to view submitted feedback entries with admin authorization."""
    admin_key = os.environ.get('ADMIN_KEY') or os.environ.get('FEEDBACK_ADMIN_KEY') or DEFAULT_ADMIN_KEY
    provided_key = request.headers.get('X-Admin-Key') or request.args.get('key')

    if not provided_key or provided_key != admin_key:
        return jsonify({'error': 'Unauthorized access. Provide key parameter or X-Admin-Key header.'}), 401

    if not os.path.exists(FEEDBACK_FILE):
        return jsonify({'count': 0, 'entries': []})
    try:
        with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = []
        return jsonify({'count': len(entries), 'entries': list(reversed(entries))})
    except (OSError, ValueError):
        return jsonify({'count': 0, 'entries': []})


@app.route('/api/feedback/clear', methods=['POST'])
def api_clear_feedback():
    """Allows authorized admin to clear feedback entries."""
    admin_key = os.environ.get('ADMIN_KEY') or os.environ.get('FEEDBACK_ADMIN_KEY') or DEFAULT_ADMIN_KEY
    data = request.get_json(silent=True) or {}
    provided_key = request.headers.get('X-Admin-Key') or request.args.get('key') or data.get('key')

    if not provided_key or provided_key != admin_key:
        return jsonify({'error': 'Unauthorized access.'}), 401

    try:
        with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2)
        return jsonify({'ok': True, 'count': 0})
    except OSError as err:
        return jsonify({'error': str(err)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)