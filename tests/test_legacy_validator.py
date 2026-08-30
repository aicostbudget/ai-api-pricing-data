import copy
import unittest

from scripts.lib import load_models
from scripts.validate import validate_pricing_contract


TOKEN_PRICING = {
    "currency": "USD",
    "unit": "1M tokens",
    "input": 1.0,
    "output": 2.0,
    "cached_input": None,
    "cache_write": None,
    "cache_write_1h": None,
    "batch_input": None,
    "batch_output": None,
}

NON_TOKEN_MODEL = {
    "pricing": {
        "currency": "USD",
        "unit": None,
        "input": None,
        "output": None,
        "cached_input": None,
        "cache_write": None,
        "cache_write_1h": None,
        "batch_input": None,
        "batch_output": None,
    },
    "pricing_components": [{
        "id": "document_parsing_pages",
        "component": "document_page",
        "modality": "document",
        "unit": "per_1000_pages",
        "amount": 1.5,
        "currency": "USD",
        "processing_mode": "standard",
        "pricing_status": "current",
        "calculation_default": False,
        "effective_from": "2026-08-27",
        "effective_until": None,
    }],
}


class LegacyValidatorPricingTests(unittest.TestCase):
    def test_current_parse_v5_passes_structured_non_token_contract(self):
        parse = next(
            model for model in load_models()
            if (model["provider_id"], model["model_id"]) == ("cohere", "parse-v5.0")
        )
        validate_pricing_contract(parse, ("cohere", "parse-v5.0"))
        self.assertIsNone(parse["pricing"]["unit"])
        self.assertTrue(all(
            parse["pricing"].get(field) is None
            for field in (
                "input", "cached_input", "output", "cache_write", "cache_write_1h",
                "batch_input", "batch_output",
            )
        ))
        component = parse["pricing_components"][0]
        self.assertEqual(
            (component["component"], component["unit"], component["amount"]),
            ("document_page", "per_1000_pages", 1.5),
        )

    def test_non_token_contract_rejects_populated_token_price(self):
        model = copy.deepcopy(NON_TOKEN_MODEL)
        model["pricing"]["input"] = 1.5
        with self.assertRaisesRegex(SystemExit, "non-token pricing must leave token fields null"):
            validate_pricing_contract(model, ("test", "non-token"))

    def test_non_token_contract_requires_nonempty_components(self):
        for components in (None, []):
            with self.subTest(components=components):
                model = copy.deepcopy(NON_TOKEN_MODEL)
                if components is None:
                    model.pop("pricing_components")
                else:
                    model["pricing_components"] = components
                with self.assertRaisesRegex(SystemExit, "requires pricing_components"):
                    validate_pricing_contract(model, ("test", "non-token"))

    def test_non_token_contract_rejects_unknown_component_or_unit(self):
        for field, value in (("component", "token_input"), ("unit", "per_request")):
            with self.subTest(field=field):
                model = copy.deepcopy(NON_TOKEN_MODEL)
                model["pricing_components"][0][field] = value
                with self.assertRaisesRegex(SystemExit, f"invalid .* {field}"):
                    validate_pricing_contract(model, ("test", "non-token"))

    def test_non_token_contract_requires_positive_finite_numeric_amount(self):
        for amount in (None, 0, -1, float("nan"), "1.5"):
            with self.subTest(amount=amount):
                model = copy.deepcopy(NON_TOKEN_MODEL)
                model["pricing_components"][0]["amount"] = amount
                with self.assertRaisesRegex(SystemExit, "invalid positive amount"):
                    validate_pricing_contract(model, ("test", "non-token"))

    def test_normal_token_model_still_passes(self):
        model = {"pricing": copy.deepcopy(TOKEN_PRICING)}
        validate_pricing_contract(model, ("test", "token"))


if __name__ == "__main__":
    unittest.main()
