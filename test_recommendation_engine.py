import unittest
from datetime import datetime
from purdue_menus_full_analysis import (
    PURDUE_TZ,
    classify_food_item,
    evaluate_item_health,
    evaluate_culinary_compatibility,
    build_optimal_plates,
    filter_open_locations,
    calculate_meal_targets,
    recommend_meals,
    _detect_cuisine_profile,
    _detect_cooking_method,
    _detect_flavor_tags,
    _assess_ingredient_certainty,
)


def _make_item(
    name: str,
    location: str = 'Windsor',
    station: str = 'Main Line',
    calories: float = 220.0,
    protein: float = 24.0,
    carbs: float = 10.0,
    fat: float = 8.0,
    sugar: float = 2.0,
    ingredients: str = 'Chicken Breast, Olive Oil, Sea Salt',
    allergens: list = None,
    is_vegetarian: bool = False,
    is_vegan: bool = False,
    start_time: str = '11:00:00',
    end_time: str = '14:00:00',
    meal_period: str = 'Lunch',
) -> dict:
    item = {
        'location': location,
        'meal_period': meal_period,
        'hours_status': f'{meal_period} until 2:00 pm',
        'closing_time': '2:00 pm',
        'start_time': start_time,
        'end_time': end_time,
        'station': station,
        'name': name,
        'calories': calories,
        'protein': protein,
        'carbs': carbs,
        'fat': fat,
        'sugar': sugar,
        'ingredients': ingredients,
        'allergens': allergens or [],
        'is_vegetarian': is_vegetarian,
        'is_vegan': is_vegan,
        'used_fallback': False,
    }
    item['_role'] = classify_food_item(item)
    item['_cuisine'] = _detect_cuisine_profile(item)
    item['_method'] = _detect_cooking_method(item)
    item['_flavors'] = _detect_flavor_tags(item)
    item['_certainty'] = _assess_ingredient_certainty(item)
    return item


class TestFeastRecommendationEngine(unittest.TestCase):

    def test_sandwich_classification_overrides_bread_keyword(self):
        item = _make_item(
            'Chicken Sandwich on Wheat Bread',
            calories=440, protein=30, carbs=42, fat=16,
            ingredients='Chicken Breast, Whole Wheat Bread, Lettuce, Tomato'
        )
        self.assertEqual(item['_role'], 'sandwich')

    def test_burger_and_standalone_bun_handling(self):
        burger = _make_item('Cheeseburger', calories=510, protein=30, carbs=38, fat=25)
        bun = _make_item('Hamburger Bun', calories=130, protein=4, carbs=24, fat=2)
        self.assertEqual(burger['_role'], 'sandwich')
        self.assertEqual(bun['_role'], 'exclude')
        allowed, _, _ = evaluate_item_health(bun, 'Mid')
        self.assertFalse(allowed)

    def test_composed_salad_classification_and_foundation(self):
        salad = _make_item(
            'Mediterranean Greek Salad',
            calories=220, protein=7, carbs=14, fat=15,
            ingredients='Romaine Lettuce, Feta Cheese, Olives, Olive Oil, Lemon',
            is_vegetarian=True,
        )
        chicken = _make_item('Lemon Herb Grilled Chicken Breast', calories=190, protein=35, carbs=1, fat=4)
        self.assertEqual(salad['_role'], 'composed_salad')
        ok, score, _ = evaluate_culinary_compatibility([('Main', chicken), ('Base', salad)], 'salad_protein')
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 75.0)

    def test_complete_burrito_and_pasta_avoid_redundant_carbs(self):
        burrito = _make_item('Carnitas Burrito', calories=560, protein=26, carbs=62, fat=20)
        pasta = _make_item('Chicken Parmesan Pasta', calories=480, protein=28, carbs=48, fat=16)
        rice = _make_item('Jasmine Rice', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True)

        self.assertEqual(burrito['_role'], 'complete_entree')
        self.assertEqual(pasta['_role'], 'pasta_entree')

        ok, _, reasons = evaluate_culinary_compatibility([('Main', pasta), ('Base', rice)], 'pasta_carb')
        self.assertFalse(ok)
        self.assertTrue(any('redundant' in r.lower() for r in reasons))

    def test_positive_culinary_compatibility_pairings(self):
        teriyaki = _make_item('Teriyaki Grilled Chicken', station='One World', calories=260, protein=28, carbs=14, fat=8)
        jasmine = _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True)
        marinara_pasta = _make_item('Penne Marinara', station='2Mato', calories=240, protein=8, carbs=46, fat=3, is_vegetarian=True)

        good_ok, good_score, _ = evaluate_culinary_compatibility([('Main', teriyaki), ('Base', jasmine)], 'protein_carb_veg')
        bad_ok, _, _ = evaluate_culinary_compatibility([('Main', teriyaki), ('Base', marinara_pasta)], 'protein_carb_veg')

        self.assertTrue(good_ok)
        self.assertGreaterEqual(good_score, 80.0)
        self.assertFalse(bad_ok)

    def test_missing_ingredient_uncertainty_and_healthiest_strictness(self):
        mystery_dish = _make_item('Mystery Glazed Chicken', ingredients='N/A', calories=320, protein=24, carbs=18, fat=14)
        verified_whole_na = _make_item('Steamed Broccoli', ingredients='N/A', calories=45, protein=3, carbs=8, fat=0.5, is_vegetarian=True, is_vegan=True)

        self.assertEqual(_assess_ingredient_certainty(mystery_dish), 'unknown')
        self.assertEqual(_assess_ingredient_certainty(verified_whole_na), 'verified_whole_food')

        high_mystery, _, _ = evaluate_item_health(mystery_dish, 'High')
        mid_mystery, _, _ = evaluate_item_health(mystery_dish, 'Mid')
        high_broccoli, _, _ = evaluate_item_health(verified_whole_na, 'High')

        self.assertFalse(high_mystery)
        self.assertTrue(mid_mystery)
        self.assertTrue(high_broccoli)

    def test_diversity_across_three_recommendations(self):
        items = [
            _make_item('Grilled Chicken Breast', station='Grill', calories=185, protein=35, carbs=0, fat=4),
            _make_item('Baked Salmon Fillet', station='Hearth', calories=235, protein=25, carbs=0, fat=14.5),
            _make_item('Carne Asada Steak', station='Latin', calories=250, protein=27, carbs=2, fat=14),
            _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True),
            _make_item('Spanish Rice', station='Latin', calories=210, protein=4.5, carbs=43, fat=2.0, is_vegetarian=True, is_vegan=True),
            _make_item('Steamed Broccoli', station='Sides', calories=45, protein=3, carbs=8, fat=0.5, is_vegetarian=True, is_vegan=True),
            _make_item('Roasted Asparagus', station='Sides', calories=40, protein=3.5, carbs=6, fat=0.4, is_vegetarian=True, is_vegan=True),
        ]
        plates = build_optimal_plates(items, meal_targets=None, meal_goal='Balanced Maintenance', health_intensity='Mid')
        self.assertEqual(len(plates), 1)
        combos = plates[0]['combos']
        self.assertEqual(len(combos), 3)
        anchors = {c['items'][0]['name'] for c in combos}
        self.assertEqual(len(anchors), 3)

    def test_time_filtering_open_and_closing_soon(self):
        lunch_item = _make_item('Grilled Chicken Breast', start_time='11:00:00', end_time='14:00:00', meal_period='Lunch')
        dinner_item = _make_item('Baked Salmon', start_time='17:00:00', end_time='20:30:00', meal_period='Dinner')

        at_1345 = datetime(2026, 11, 14, 13, 45, tzinfo=PURDUE_TZ)
        open_now = filter_open_locations([lunch_item, dinner_item], current_time=at_1345)
        self.assertEqual(len(open_now), 1)
        self.assertEqual(open_now[0]['name'], 'Grilled Chicken Breast')
        self.assertIn('Closes at', open_now[0]['hours_status'])

    def test_dri_minor_safeguard(self):
        minor_targets = calculate_meal_targets(
            sex='M', age=16, weight_lbs=145, height_in=69,
            activity_level='Active', meals_per_day=3,
            meal_goal='Lean Cut / Fat Loss', health_intensity='High'
        )
        adult_targets = calculate_meal_targets(
            sex='M', age=20, weight_lbs=145, height_in=69,
            activity_level='Active', meals_per_day=3,
            meal_goal='Lean Cut / Fat Loss', health_intensity='High'
        )
        self.assertTrue(minor_targets['is_minor_safeguarded'])
        self.assertGreater(minor_targets['daily']['calories'], adult_targets['daily']['calories'])

    def test_all_modes_and_empty_menu_handling(self):
        empty_res = recommend_meals(prebuilt_items=[])
        self.assertEqual(empty_res['recommendations'], [])

        sample_items = [
            _make_item('Teriyaki Chicken', station='One World', calories=270, protein=26, carbs=16, fat=9, ingredients='Chicken, Soy Sauce, Ginger, Garlic, Honey'),
            _make_item('Grilled Chicken Breast', station='Grill', calories=185, protein=35, carbs=0, fat=4, ingredients='Chicken Breast, Olive Oil, Sea Salt'),
            _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, ingredients='Jasmine Rice, Water', is_vegetarian=True, is_vegan=True),
            _make_item('Steamed Broccoli', station='Grill', calories=45, protein=3, carbs=8, fat=0.5, ingredients='Broccoli, Water', is_vegetarian=True, is_vegan=True),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        for mode in ('High', 'Mid', 'Low'):
            res = recommend_meals(health_intensity=mode, prebuilt_items=sample_items, current_time=lunch_time)
            self.assertEqual(len(res['recommendations']), 1)
            self.assertGreaterEqual(len(res['recommendations'][0]['combos']), 1)
            self.assertIn('score_breakdown', res['recommendations'][0]['combos'][0])

    def test_seed_oil_rejected_from_healthy_and_pure_health(self):
        canola_item = _make_item('Sauteed Green Beans', ingredients='Green Beans, Canola Oil, Salt')
        soy_item = _make_item('Roast Chicken', ingredients='Chicken, Soybean Oil, Spices')
        veg_oil_item = _make_item('Roasted Potatoes', ingredients='Potatoes, Vegetable Oil, Sea Salt')

        for item in (canola_item, soy_item, veg_oil_item):
            allowed_high, _, reason_high = evaluate_item_health(item, 'High')
            self.assertFalse(allowed_high)
            self.assertIn('contains seed oils', reason_high)

            allowed_pure, _, reason_pure = evaluate_item_health(item, 'Extreme')
            self.assertFalse(allowed_pure)
            self.assertIn('contains seed oils', reason_pure)

    def test_deep_fried_rejected_from_healthy(self):
        fried_steak = _make_item('Country Fried Steak', calories=420, protein=24, carbs=30, fat=22, ingredients='Beef, Battered, Fried, Flour, Salt')
        allowed, _, reason = evaluate_item_health(fried_steak, 'High')
        self.assertFalse(allowed)
        self.assertIn('deep-fried', reason)

    def test_unverified_ingredients_rejected_from_healthy(self):
        unknown_dish = _make_item('Mystery Casserole', ingredients='N/A')
        allowed, _, reason = evaluate_item_health(unknown_dish, 'High')
        self.assertFalse(allowed)
        self.assertIn('unverified ingredients', reason)

    def test_balanced_mode_accepts_normal_entrees_with_preservatives(self):
        fajitas = _make_item(
            'Shrimp Fajitas', calories=260, protein=22, carbs=12, fat=8,
            ingredients='Shrimp, Bell Peppers, Onions, Canola Oil, Spices, Potassium Sorbate, Sodium Benzoate'
        )
        allowed, _, _ = evaluate_item_health(fajitas, 'Mid')
        self.assertTrue(allowed)

    def test_clean_salad_and_bowl_not_excluded_by_name(self):
        clean_salad = _make_item(
            'Mediterranean Quinoa Salad', calories=240, protein=9, carbs=32, fat=7,
            ingredients='Quinoa, Cucumbers, Tomatoes, Feta Cheese, Kalamata Olives, Extra Virgin Olive Oil, Lemon Juice, Salt'
        )
        allowed, _, reason = evaluate_item_health(clean_salad, 'High')
        self.assertTrue(allowed)
        self.assertIn('Verified seed-oil-free', reason)

    def test_healthy_mode_honest_empty_when_no_clean_items(self):
        seed_oil_only = [
            _make_item('Fried Chicken Tender', calories=320, protein=20, carbs=18, fat=18, ingredients='Chicken, Soybean Oil, Flour'),
            _make_item('French Fries', calories=280, protein=3, carbs=38, fat=14, ingredients='Potatoes, Canola Oil, Salt'),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        res = recommend_meals(health_intensity='High', prebuilt_items=seed_oil_only, current_time=lunch_time)
        self.assertEqual(len(res['recommendations']), 1)
        self.assertEqual(res['recommendations'][0]['combos'], [])
        self.assertIn('No verified seed-oil-free meals available', res['recommendations'][0]['no_qualifying_reason'])


if __name__ == '__main__':
    unittest.main()