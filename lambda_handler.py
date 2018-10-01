#!/usr/bin/env python3
from collections import OrderedDict
from string import Template
from traceback import print_exc

MAX_RECURSION = 16

functions = {}

def handler(event, context):
    global operations
    print("TuringFormation Event=%s" % (event,))
    fragment = event["fragment"]
    request_id = event["requestId"]
    params = event["params"]
    template_params = event["templateParameterValues"]
    status = "success"

    try:
        process_fragment(parent=None, key=None, fragment=fragment)
    except Exception as e:
        print(str(e))
        print_exc()
        status = "failed"
    
    return {
        "fragment": fragment,
        "requestId": request_id,
        "status": status,
    }

def process_fragment(parent, key, fragment):
    global functions

    parent_key = key

    if isinstance(fragment, dict):
        # Depth-first processing -- only process function call after values
        # have been processed.
        
        # Since fragment may change, keep processing until all keys have been
        # processed.
        fragment_keys_seen = set()

        for i in range(MAX_RECURSION):
            # Change view of keys into actual set so we operate consistently
            # even if keys are added.
            fragment_keys = list(fragment.keys())
            new_fragment_key_seen = False

            for fragment_key in fragment_keys:
                if fragment_key not in fragment_keys_seen:
                    new_fragment_key_seen = True
                    fragment_keys_seen.add(fragment_key)
                    process_fragment(
                        parent=fragment, key=fragment_key,
                        fragment=fragment[fragment_key])
            
            if not new_fragment_key_seen:
                break
        else:
            # We recursed the maximum number of times. Error out if we still
            # haven't finished processing
            if fragment.keys() - fragment_keys_seen:
                raise RecursionError("Maximum recursion on mapping node")
        
        # See if we have a function call.
        for key, value in fragment.items():
            if isinstance(key, str) and key.startswith("Turing::"):
                # Turing function call. This must be the only element in the
                # dict.
                if len(fragment) != 1:
                    raise ValueError(
                        "Function call %s must be the only element in "
                        "mapping" % key)

                function = functions.get(key)
                if not function:
                    raise ValueError("Unknown function %s" % key)
                
                function(parent=parent, key=parent_key, fragment=value)
    elif isinstance(fragment, list):
        # Lists can be mutated safely during iteration.
        for i, item in enumerate(fragment):
            process_fragment(parent=fragment, key=i, fragment=item)

    # Otherwise fragment is an int, str, or other atomic item.
    return

def splice(parent, key, fragment):
    """
    [a, b, {"Fn::Splice": [c, d]}, e, f] ->
        [a, b, c, d, e, f]
 5, f: 6} ->
        {a: 1, b: 2, c: 3, d: 4, e: 5, f: 6}
    """
    if isinstance(parent, list):
        if not isinstance(fragment, list):
            raise TypeError(
                "Turing::Splice cannot splice %s into mapping" %
                type(fragment).__name__)
        parent[key:key+1] = fragment
    else:
        raise TypeError(
            "Turing::Splice cannot splice %s into %s" %
            type(fragment).__name__, type(parent).__name__)
    
    return
functions["Turing::Splice"] = splice

def for_each(parent, key, fragment):
    """
    {"Fn::ForEach": [[x, [a, b, ...], y, [c, d, ...], ...], body]} ->
        [eval1, eval2, eval3, ...]
    Perform substitutions on string elements within body, replacing each
    variable found with the corresponding value.

    If a variable has no elements in its iteration list, body is never
    evaluated and an empty list is returned.
    """
    usage_msg = ("Turing::ForEach argument must be a 2-element list of "
                 "[[x, [a, b, ...], y, [c, d, ...], ...], body]: %s")
    if not isinstance(fragment, list):
        raise TypeError(usage_msg % (fragment,))
    if len(fragment) != 2:
        raise ValueError(usage_msg % (fragment,))

    # iteration_specs is the first element that specifies the variables to
    # set and values to iterate over.
    iteration_specs = fragment[0]
    body = fragment[1]

    var_names = []
    var_values = []

    if not isinstance(iteration_specs, list):
        raise TypeError(usage_msg % (fragment,))
    for iteration_spec in iteration_specs:
        if not isinstance(iteration_spec, list):
            raise TypeError(usage_msg % (fragment,))
        if len(iteration_spec) != 2:
            raise ValueError(usage_msg % (iteration_spec,))
        
        name = iteration_spec[0]
        values = iteration_spec[1]

        if not isinstance(name, str) or not isinstance(values, list):
            raise TypeError(usage_msg % (iteration_spec,))
        
        var_names.append(name)
        var_values.append([str(el) for el in values])

    # If any variable values have no elements, return an empty list; otherwise,
    # our first iteration in the loop will fail with an IndexError.
    if any([len(values) == 0 for values in var_values]):
        parent[key] = []
        return
    
    # Even if n_variables is 0, the logic below still works.
    n_variables = len(var_names)    

    # Keep track of where we are in iterating each variable and the number of
    # values for each variable.
    indexes = [0] * n_variables
    n_variable_values = [len(var_values[i]) for i in range(n_variables)]

    result = []

    # Get the starting value for each variable
    current_values = {
        var_names[i]: var_values[i][0]
        for i in range(n_variables)
    }

    while True:
        result.append(json_string_sub(body, current_values))

        # Go to the next value for the innermost variable.
        for i in range(n_variables - 1, -1, -1):
            var_name = var_names[i]
            new_index = indexes[i] + 1
            if new_index < n_variable_values[i]:
                # Still have another value for this variable. Go on to the next
                # iteration of the loop.
                indexes[i] = new_index
                current_values[var_name] = var_values[i][new_index]
                break
            
            # Ran out of values for this variable; reset to 0 and go on to
            # the next variable.
            indexes[i] = 0
            current_values[var_name] = var_values[i][0]
        else:
            # All variables completed.
            break

    parent[key] = result
    return

functions["Turing::ForEach"] = for_each
functions["Turing::Foreach"] = for_each

def json_string_sub(body, mapping):
    """
    T = Union[str, int, float, list, dict]
    json_string_sub(body: T, mapping: Dict[str, str]) -> T
    Perform variable substitution on every string in body with the values
    in mapping.
    """
    if isinstance(body, dict):
        return {
            json_string_sub(key, mapping): json_string_sub(value, mapping)
            for key, value in body.items()
        }
    elif isinstance(body, list):
        return [json_string_sub(el, mapping) for el in body]
    elif isinstance(body, str):
        return Template(body).safe_substitute(mapping)
    else:
        return body
