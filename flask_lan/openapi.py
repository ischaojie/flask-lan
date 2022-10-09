from functools import partial, wraps
from inspect import Parameter as InspectParameter
from inspect import signature
from typing import Callable, Dict, Iterator, List, Optional, Union

from flask import current_app, request
from pydantic import BaseModel
from werkzeug.routing import Map, Rule

from flask_lan.schemas import (
    Components,
    Info,
    MediaType,
    OpenAPI,
    Operation,
    Parameter,
    ParameterInType,
    PathItem,
    Reference,
    RequestBody,
    Response,
    Schema,
)


def gen_openapi_spec(
    map: Map,
    view_functions: Dict[str, Callable],
    title: str,
    version: str,
    openapi_version: str = "3.0.2",
    desc: Optional[str] = None,
) -> OpenAPI:
    """
    Generate openapi specification schema

    title: openapi title
    version: current api version
    """
    exclude_path = ("/swagger", "/openapi", "/redoc")

    info = Info(title=title, description=desc, version=version)

    paths_with_rules: Dict[str, Dict[str, Rule]] = {}
    for rule in map.iter_rules():
        path = rule.rule
        if path in exclude_path:
            continue
        # TODO: support more http methods
        methods_with_rule = (
            {method.lower(): rule for method in rule.methods} if rule.methods else {}
        )
        paths_with_rules.setdefault(path, methods_with_rule).update(methods_with_rule)
    paths = {
        path: make_pathitem(method_rules, view_functions)
        for path, method_rules in paths_with_rules.items()
    }

    components = Components(schemas=make_schemas(map.iter_rules(), view_functions))
    return OpenAPI(
        openapi=openapi_version,
        info=info,
        paths=paths,
        components=components,
    )


def make_pathitem(
    method_rules: Dict[str, Rule], view_functions: Dict[str, Callable]
) -> PathItem:
    items = {}
    for method, rule in method_rules.items():
        view_func = view_functions.get(rule.endpoint, None)
        if not view_func:
            continue
        items[method] = make_operation(rule, view_func)
    for method, rule in method_rules.items():
        view_func = view_functions.get(rule.endpoint, None)
        if view_func:
            items[method] = make_operation(rule, view_func)
    return PathItem(**items)


def make_operation(rule: Rule, view_func: Callable) -> Operation:

    sig = signature(view_func)

    # make params
    parameters = []
    request_body_content = {}
    request_body_required = False
    for name, param in sig.parameters.items():
        _type = param.annotation
        # this is path params
        if name in rule.arguments:
            parameters.append(
                Parameter(name=name, in_=ParameterInType.path, required=True)
            )
        # this is request body params
        elif issubclass(_type, BaseModel):
            request_body_content["application/json"] = MediaType(
                schema=Reference(ref=f"#/components/schemas/{_type.__name__}")
            )
            request_body_required = True
        # this is query body
        else:
            parameters.append(
                Parameter(
                    name=name,
                    in_=ParameterInType.query,
                    required=param.default is InspectParameter.empty,
                )
            )

    if not request_body_content:
        req_body = None
    else:
        req_body = RequestBody(
            content=request_body_content, required=request_body_required
        )

    # make responses
    sig.return_annotation
    # TODO: rsp
    responses = {"200": Response(description="OK")}
    return Operation(
        parameters=parameters or None,
        requestBody=req_body,
        responses=responses,
    )


def make_schemas(rules: Iterator[Rule], view_functions: Dict[str, Callable]):
    schemas: Dict[str, Union[Schema, Reference]] = {}
    for rule in rules:
        view_func = view_functions.get(rule.endpoint, None)
        if not view_func:
            return {}
        sig = signature(view_func)
        for _, param in sig.parameters.items():
            _type = param.annotation
            if issubclass(_type, BaseModel):
                schemas[_type.__name__] = Schema(**_type.schema())

    return schemas


def docs(
    f: Callable,
    *,
    tags: Optional[List[str]] = None,
    summary: Optional[str] = None,
    desc: Optional[str] = None,
):
    """docs decorator"""
    if f is None:
        return partial(docs, tags=tags)

    @wraps(f)
    def wrapper(*args, **kwargs):
        r = f(*args, **kwargs)
        config = current_app.extensions.get("lan", {})
        url_rule = request.url_rule
        if url_rule:
            doc_schema = {
                "tags": tags,
                "summary": summary,
                "description": desc,
                "operationId": url_rule.endpoint,
            }
            config.setdefault(url_rule.endpoint, {}).update(url_rule.endpoint, doc_schema)
        current_app.extensions["lan"] = config

        return r

    return wrapper
