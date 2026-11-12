import os
from flask import Flask, render_template, request, jsonify

try:
    from purdue_menus_full_analysis import recommend_meals, _parse_user_time_input
except ImportError:
    from purdue_menus_full_analysis import recommend_meals, _parse_user_time_input

app = Flask(__name__)


@app.route('/')
def index():
    """Serves the main mobile-friendly Purdue Dining Optimizer webpage."""
    return render_template('index.html')


@app.route('/api/recommend', methods=['POST'])
def api_recommend():
    """Receives user biometrics and preferences as JSON and returns meal recommendations."""
    data = request.get_json(silent=True) or {}

    try:
        sex = str(data.get('sex', 'M')).strip() or 'M'
        age = int(data.get('age', 18))
        weight_lbs = float(data.get('weight_lbs', 155))
        height_in = float(data.get('height_in', 72))
        activity_level = str(data.get('activity_level', 'Moderate')).strip() or 'Moderate'
        meals_per_day = int(data.get('meals_per_day', 2))
        meal_goal = str(data.get('meal_goal', 'High Protein')).strip() or 'High Protein'
        health_intensity = str(data.get('health_intensity', 'High')).strip() or 'High'
        include_quick_bites = bool(data.get('include_quick_bites', False))

        sim_raw = str(data.get('sim_time', '')).strip()
        sim_time = _parse_user_time_input(sim_raw) if sim_raw else None

        result = recommend_meals(
            sex=sex,
            age=age,
            weight_lbs=weight_lbs,
            height_in=height_in,
            activity_level=activity_level,
            meals_per_day=meals_per_day,
            meal_goal=meal_goal,
            health_intensity=health_intensity,
            include_quick_bites=include_quick_bites,
            current_time=sim_time,
        )
        return jsonify(result)

    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port,)