import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify
from purdue_menus_full_analysis import recommend_meals, _parse_user_time_input

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
FEEDBACK_FILE = os.path.join(BASE_DIR, 'feast_feedback.json')
PURDUE_TZ = ZoneInfo("America/Indiana/Indianapolis")


@app.route('/')
def index():
    """Serves the Feast campus dining companion webpage."""
    return render_template('index.html')


@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    """Receives mode, allergy/dietary filters, and optional DRI biometrics as JSON."""
    data = request.get_json(silent=True) or {}

    try:
        health_intensity = str(data.get('health_intensity', 'High')).strip() or 'High'
        dri_enabled = bool(data.get('dri_enabled', False))
        include_quick_bites = bool(data.get('include_quick_bites', False))
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
            include_quick_bites=include_quick_bites,
            current_time=sim_time,
        )
        return jsonify(result)

    except ValueError as val_err:
        return jsonify({'error': str(val_err)}), 400
    except Exception as exc:
        return jsonify({'error': f'Unexpected error: {exc}'}), 500


@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    """Stores student feedback, dish requests, and bug reports cleanly."""
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