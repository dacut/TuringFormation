#!/usr/bin/env python3
from unittest import TestCase
from uuid import uuid4
import lambda_handler

class TestLambdaHandler(TestCase):
    def run_handler(self, fragment, template_params=None, request_id=None):
        if template_params is None:
            template_params = {}
        
        if request_id is None:
            request_id = uuid4()
        
        return lambda_handler.handler({
            "fragment": fragment,
            "requestId": request_id,
            "params": {},
            "templateParameterValues": template_params,
        }, None)

    def test_foreach_string_sub(self):
        result = self.run_handler(
            {"Hello": {"Turing::ForEach": [
                [["x", [1, 2, 3]]],
                "Hello ${x}"]}})
        self.assertEqual(
            result["fragment"], {"Hello": ["Hello 1", "Hello 2", "Hello 3"]})
    
    def test_splice_list(self):
        result = self.run_handler(
            ["a", "b", {"Turing::Splice": ["c", "d"]}, "e", "f"])
        self.assertEqual(result["fragment"], ["a", "b", "c", "d", "e", "f"])
        