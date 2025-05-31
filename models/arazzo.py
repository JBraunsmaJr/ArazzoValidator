import json
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import re
from pathlib import Path
import yaml
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError
from pydantic import (
    BaseModel, Field, ValidationError,
    model_validator, field_validator,
    RootModel, ConfigDict
)

class SpecificationExtensionsMixin(BaseModel):
    """
    This allows "x-" prefixed properties as per the Arazzo spec.
    """
    model_config = ConfigDict(
        extra='allow',  # Allows `x-` extensions for models with explicit fields
        alias_generator=to_camel,
        populate_by_name=True
    )

def validate_unique_items(v: List[Any], field_name: str) -> List[Any]:
    """
    Custom validator to enforce unique_items for lists.
    For complex objects (like other BaseModels), it uses their JSON representation
    for hashing to ensure uniqueness by value.
    """
    # Let Pydantic's type checking handle this if type is wrong
    if not isinstance(v, list):
        return v

    seen = set()
    duplicates_found = []

    for item in v:
        try:
            if isinstance(item, BaseModel):
                hashable_item = item.model_dump_json()
            else:
                hashable_item = item
        except TypeError:
            hashable_item = str(item)

        if hashable_item in seen:
            duplicates_found.append(item)
        else:
            seen.add(hashable_item)

    if duplicates_found:
        distinct_duplicates_repr = sorted([str(d) for d in set(duplicates_found)])  # Sort for consistent error output
        raise ValueError(
            f"List for '{field_name}' must contain unique items. Found duplicates: {distinct_duplicates_repr}.")

    return v

class Info(SpecificationExtensionsMixin):
    """
    Provides metadata about the Arazzo description.
    Corresponds to #/$defs/info
    """
    title: str = Field(..., description="A human readable title of the Arazzo Description")
    summary: Optional[str] = Field(None, description="A short summary of the Arazzo Description")
    description: Optional[str] = Field(None,
                                       description="A description of the purpose of the workflows defined. CommonMark syntax MAY be used for rich text representation")
    version: str = Field(...,
                         description="The version identifier of the Arazzo document (which is distinct from the Arazzo Specification version)")


class SourceDescription(SpecificationExtensionsMixin):
    """
    Describes a source description (such as an OpenAPI description)
    Corresponds to #/$defs/source-description-object
    """

    class SourceType(str, Enum):
        ARAZZO = "arazzo"
        OPENAPI = "openapi"

    name: str = Field(..., description="A unique name for the source description", pattern=r"^[A-Za-z0-9_\\-]+$")
    url: str = Field(..., description="A URL to a source description to be used by a workflow",
                     json_schema_extra={"format": "uri-reference"})  # Add format hint for tooling

    @field_validator('url')
    @classmethod
    def validate_uri_reference(cls, v: str) -> str:
        # A basic check for uri-reference to ensure no whitespace.
        if re.search(r"\s", v):
            raise ValueError("URL must not contain whitespace.")
        return v

    type: Optional[SourceType] = Field(None, description="The type of source description")


class Schema(RootModel):
    """
    Represents a JSON Schema 2020-12 object.
    Corresponds to #/$defs/schema, which is a $ref to the full JSON Schema spec.
    """
    root: Dict[str, Any]


class ReusableObject(SpecificationExtensionsMixin):
    """
    A simple object to allow referencing of objects contained within the Components Object.
    Corresponds to #/$defs/reusable-object
    """
    reference: str = Field(..., description="A runtime expression used to reference the desired object")
    value: Optional[Any] = Field(None, description="Sets a value of the referenced parameter")


class Parameter(SpecificationExtensionsMixin):
    """
    Describes a single step parameter.
    Corresponds to #/$defs/parameter-object
    """

    class InLocation(str, Enum):
        PATH = "path"
        QUERY = "query"
        HEADER = "header"
        COOKIE = "cookie"

    name: str = Field(..., description="The name of the parameter")
    in_: Optional[InLocation] = Field(None, alias="in",
                                      description="The named location of the parameter")
    value: Any = Field(..., description="The value to pass in the parameter")


class PayloadReplacement(SpecificationExtensionsMixin):
    """
    Describes a location within a payload (e.g., a request body) and a value to set within the location.
    Corresponds to #/$defs/payload-replacement-object
    """
    target: str = Field(...,
                        description="A JSON Pointer or XPath Expression which MUST be resolved against the request body")
    value: str = Field(..., description="The value set within the target location")


class RequestBody(SpecificationExtensionsMixin):
    """
    The request body to pass to an operation as referenced by operation_id or operation_path.
    Corresponds to #/$defs/request-body-object
    """
    content_type: Optional[str] = Field(None, description="The Content-Type for the request content")
    payload: Optional[Any] = Field(None,
                                   description="The actual request body content (can be any JSON type).")
    replacements: Optional[List[PayloadReplacement]] = Field(None,
                                                             description="A list of locations and values to set within a payload")

    @field_validator('replacements')
    @classmethod
    def validate_replacements_uniqueness(cls, v: Optional[List[PayloadReplacement]]) -> Optional[
        List[PayloadReplacement]]:
        if v is not None:
            validate_unique_items(v, "replacements")
        return v


class CriterionExpressionType(SpecificationExtensionsMixin):
    """
    An object used to describe the type and version of an expression used within a Criterion Object.
    Corresponds to #/$defs/criterion-expression-type-object
    """

    class ExpressionType(str, Enum):
        JSONPATH = "jsonpath"
        XPATH = "xpath"

    class JsonPathVersion(str, Enum):
        DRAFT_GOESSNER = "draft-goessner-dispatch-jsonpath-00"

    class XPathVersion(str, Enum):
        XPATH_1_0 = "xpath-10"
        XPATH_2_0 = "xpath-20"
        XPATH_3_0 = "xpath-30"

    type: ExpressionType = Field(..., description="The type of condition to be applied")
    version: str = Field(..., description="A short hand string representing the version of the expression type")

    @model_validator(mode='after')
    def check_conditional_version(self) -> 'CriterionExpressionType':
        if self.type == self.ExpressionType.JSONPATH and self.version != self.JsonPathVersion.DRAFT_GOESSNER:
            raise PydanticCustomError(
                'invalid_jsonpath_version',
                'For jsonpath type, version must be "{required_version}".',
                {'required_version': self.JsonPathVersion.DRAFT_GOESSNER.value}
            )
        if self.type == self.ExpressionType.XPATH and self.version not in [
            self.XPathVersion.XPATH_1_0.value, self.XPathVersion.XPATH_2_0.value, self.XPathVersion.XPATH_3_0.value
        ]:
            raise PydanticCustomError(
                'invalid_xpath_version',
                'For xpath type, version must be one of "{allowed_versions}".',
                {'allowed_versions': ", ".join([v.value for v in self.XPathVersion])}
            )
        return self


class Criterion(SpecificationExtensionsMixin):
    """
    An object used to specify the context, conditions, and condition types
    that can be used to prove or satisfy assertions.
    Corresponds to #/$defs/criterion-object
    """

    class ConditionType(str, Enum):
        SIMPLE = "simple"
        REGEX = "regex"
        JSONPATH = "jsonpath"
        XPATH = "xpath"

    context: Optional[str] = Field(None,
                                   description="A runtime expression used to set the context for the condition to be applied on")
    condition: str = Field(..., description="The condition to apply")

    type: Union[ConditionType, CriterionExpressionType] = Field(
        ConditionType.SIMPLE,
        description="The type of condition to be applied"
    )
    """
    Option 1: 'type' as string enum (simple, regex, jsonpath, xpath) with default "simple"
    Option 2: 'type' as CriterionExpressionType object (for jsonpath, xpath with version)
    """

    @model_validator(mode='after')
    def check_dependent_required(self) -> 'Criterion':
        """
        "dependentRequired": {"type": ["context"]}
        If the 'type' field is present (which it always is, due to default),
        then context is required. The schema's `anyOf` for `type` suggests specific types
        like "jsonpath" or "xpath" explicitly imply the need for `context`.
        We enforce context for 'jsonpath' and 'xpath' types.
        :return:
        """
        if (
                (isinstance(self.type, str) and self.type in [self.ConditionType.JSONPATH, self.ConditionType.XPATH]) or
                isinstance(self.type, CriterionExpressionType)
        ) and self.context is None:
            raise PydanticCustomError(
                'missing_context_for_expression_type',
                'Criterion with type "{type_value}" requires a "context".',
                {'type_value': self.type if isinstance(self.type, str) else self.type.type}
            )
        return self


class SuccessAction(SpecificationExtensionsMixin):
    """
    A single success action which describes an action to take upon success of a workflow step.
    Corresponds to #/$defs/success-action-object
    """

    class ActionType(str, Enum):
        END = "end"
        GOTO = "goto"

    name: str = Field(..., description="The name of the success action")
    type: ActionType = Field(..., description="The type of action to take")
    workflow_id: Optional[str] = Field(None,
                                       description="The workflowId referencing an existing workflow within the Arazzo description to transfer to upon success of the step")
    step_id: Optional[str] = Field(None, description="The stepId to transfer to upon success of the step")
    criteria: Optional[List[Criterion]] = Field(
        None, min_length=1, description="A list of assertions to determine if this action SHALL be executed"
    )

    @field_validator('criteria')
    @classmethod
    def validate_criteria_uniqueness(cls, v: Optional[List[Criterion]]) -> Optional[List[Criterion]]:
        if v is not None:
            validate_unique_items(v, "criteria")
        return v

    @model_validator(mode='after')
    def check_conditional_goto(self) -> 'SuccessAction':
        if self.type == self.ActionType.GOTO:
            if not (self.workflow_id or self.step_id):
                raise PydanticCustomError(
                    'goto_missing_target',
                    'Success action of type "{type}" must specify either "workflowId" or "stepId".',
                    {'type': self.type.value}
                )
            if self.workflow_id and self.step_id:
                raise PydanticCustomError(
                    'goto_exclusive_target',
                    'Success action of type "{type}" cannot specify both "workflowId" and "stepId".',
                    {'type': self.type.value}
                )
        return self


class FailureAction(SpecificationExtensionsMixin):
    """
    A single failure action which describes an action to take upon failure of a workflow step.
    Corresponds to #/$defs/failure-action-object
    """

    class ActionType(str, Enum):
        END = "end"
        GOTO = "goto"
        RETRY = "retry"

    name: str = Field(..., description="The name of the failure action")
    type: ActionType = Field(..., description="The type of action to take")
    workflow_id: Optional[str] = Field(None,
                                       description="The workflowId referencing an existing workflow within the Arazzo description to transfer to upon failure of the step")
    step_id: Optional[str] = Field(None, description="The stepId to transfer to upon failure of the step")
    retry_after: Optional[float] = Field(None,
                                         description="A non-negative decimal indicating the seconds to delay after the step failure before another attempt SHALL be made",
                                         ge=0)
    retry_limit: Optional[int] = Field(None,
                                       description="A non-negative integer indicating how many attempts to retry the step MAY be attempted before failing the overall step",
                                       ge=0)
    criteria: Optional[List[Criterion]] = Field(
        None, description="A list of assertions to determine if this action SHALL be executed"
    )

    @field_validator('criteria')
    @classmethod
    def validate_criteria_uniqueness(cls, v: Optional[List[Criterion]]) -> Optional[List[Criterion]]:
        if v is not None:
            validate_unique_items(v, "criteria")
        return v

    @model_validator(mode='after')
    def check_conditional_goto_retry(self) -> 'FailureAction':
        if self.type in [self.ActionType.GOTO, self.ActionType.RETRY]:
            if not (self.workflow_id or self.step_id):
                raise PydanticCustomError(
                    'goto_retry_missing_target',
                    'Failure action of type "{type}" must specify either "workflowId" or "stepId".',
                    {'type': self.type.value}
                )
            if self.workflow_id and self.step_id:
                raise PydanticCustomError(
                    'goto_retry_exclusive_target',
                    'Failure action of type "{type}" cannot specify both "workflowId" and "stepId".',
                    {'type': self.type.value}
                )
        if self.type == self.ActionType.RETRY:
            if self.retry_after is None:
                raise PydanticCustomError(
                    'retry_missing_retry_after',
                    'Failure action of type "{type}" must specify "retryAfter".',
                    {'type': self.type.value}
                )
        return self


class Step(SpecificationExtensionsMixin):
    """
    Describes a single workflow step which MAY be a call to an API operation
    (OpenAPI Operation Object or another Workflow Object).
    Corresponds to #/$defs/step-object
    """
    step_id: str = Field(..., description="Unique string to represent the step")
    description: Optional[str] = Field(None,
                                       description="A description of the step. CommonMark syntax MAY be used for rich text representation")
    operation_id: Optional[str] = Field(None, description="The name of an existing, resolvable operation")
    operation_path: Optional[str] = Field(None,
                                          description="A reference to a Source combined with a JSON Pointer to reference an operation")
    workflow_id: Optional[str] = Field(None,
                                       description="The workflowId referencing an existing workflow within the Arazzo description")

    # Step parameters have conditional 'items' constraints based on operationId/Path vs workflowId.
    parameters: Optional[List[Union['Parameter', 'ReusableObject']]] = Field(
        None,
        description="A list of parameters that MUST be passed to an operation or workflow as referenced by operationId, operationPath, or workflowId"
    )

    @field_validator('parameters')
    @classmethod
    def validate_parameters_uniqueness(cls, v: Optional[List[Union['Parameter', 'ReusableObject']]]) -> Optional[
        List[Union['Parameter', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "parameters")
        return v

    request_body: Optional[RequestBody] = Field(None,
                                                description="The request body to pass to an operation as referenced by operationId or operationPath")
    success_criteria: Optional[List['Criterion']] = Field(
        None, min_length=1, description="A list of assertions to determine the success of the step"
    )

    @field_validator('success_criteria')
    @classmethod
    def validate_success_criteria_uniqueness(cls, v: Optional[List['Criterion']]) -> Optional[List['Criterion']]:
        if v is not None:
            validate_unique_items(v, "success_criteria")
        return v

    on_success: Optional[List[Union['SuccessAction', 'ReusableObject']]] = Field(
        None, description="An array of success action objects that specify what to do upon step success"
    )

    @field_validator('on_success')
    @classmethod
    def validate_on_success_uniqueness(cls, v: Optional[List[Union['SuccessAction', 'ReusableObject']]]) -> Optional[
        List[Union['SuccessAction', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "on_success")
        return v

    on_failure: Optional[List[Union['FailureAction', 'ReusableObject']]] = Field(
        None, description="An array of failure action objects that specify what to do upon step failure"
    )

    @field_validator('on_failure')
    @classmethod
    def validate_on_failure_uniqueness(cls, v: Optional[List[Union['FailureAction', 'ReusableObject']]]) -> Optional[
        List[Union['FailureAction', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "on_failure")
        return v

    outputs: Optional[Dict[str, str]] = Field(
        None, description="A map between a friendly name and a dynamic output value defined using a runtime expression"
    )

    @model_validator(mode='after')
    def check_conditional_step_target(self) -> 'Step':
        # oneOf: operation_id, operation_path, or workflow_id must be present
        target_fields = [self.operation_id, self.operation_path, self.workflow_id]
        present_targets = [t for t in target_fields if t is not None]

        if not present_targets:
            raise PydanticCustomError(
                'step_missing_target_type',
                'Step must specify one of "operationId", "operationPath", or "workflowId".',
                {}
            )
        if len(present_targets) > 1:
            raise PydanticCustomError(
                'step_exclusive_target_type',
                'Step cannot specify more than one of "operationId", "operationPath", or "workflowId".',
                {}
            )

        # allOf conditions for parameters based on step type
        if self.parameters:
            if self.operation_id or self.operation_path:
                # If operation, parameters can be ReusableObject or Parameter with 'in' required
                for i, param in enumerate(self.parameters):
                    if isinstance(param, Parameter):
                        if param.in_ is None:
                            raise PydanticCustomError(
                                'parameter_in_required_for_operation',
                                'Parameter at index {parameter_index} in operation-based step must have "in" field.',
                                {'parameter_index': i}
                            )
                    elif not isinstance(param, ReusableObject):
                        raise PydanticCustomError(
                            'invalid_parameter_type_for_operation',
                            'Parameter at index {parameter_index} in operation-based step must be a Parameter or ReusableObject.',
                            {'parameter_index': i}
                        )
            elif self.workflow_id:
                # If workflow, parameters can be ReusableObject or Parameter (no 'in' required)
                for i, param in enumerate(self.parameters):
                    if not isinstance(param, (Parameter, ReusableObject)):
                        raise PydanticCustomError(
                            'invalid_parameter_type_for_workflow',
                            'Parameter at index {parameter_index} in workflow-based step must be a Parameter or ReusableObject.',
                            {'parameter_index': i}
                        )
        return self


class Workflow(SpecificationExtensionsMixin):
    """
    Describes the steps to be taken across one or more APIs to achieve an objective.
    Corresponds to #/$defs/workflow-object
    """
    workflow_id: str = Field(..., description="Unique string to represent the workflow")
    summary: Optional[str] = Field(None, description="A summary of the purpose or objective of the workflow")
    description: Optional[str] = Field(None,
                                       description="A description of the workflow. CommonMark syntax MAY be used for rich text representation")
    inputs: Optional[Schema] = Field(None,
                                     description="A JSON Schema 2020-12 object representing the input parameters used by this workflow")
    depends_on: Optional[List[str]] = Field(
        None, description="A list of workflows that MUST be completed before this workflow can be processed"
    )

    @field_validator('depends_on')
    @classmethod
    def validate_depends_on_uniqueness(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            validate_unique_items(v, "depends_on")
        return v

    steps: List['Step'] = Field(
        ..., min_length=1,
        description="An ordered list of steps where each step represents a call to an API operation or to another workflow"
    )

    @field_validator('steps')
    @classmethod
    def validate_steps_uniqueness(cls, v: List['Step']) -> List['Step']:
        if v is not None:
            # For uniqueness of Step objects, we must compare by step_id, not object identity.
            step_ids = [step.step_id for step in v]
            if len(step_ids) != len(set(step_ids)):
                seen_ids = set()
                duplicate_ids = []
                for s_id in step_ids:
                    if s_id in seen_ids:
                        duplicate_ids.append(s_id)
                    else:
                        seen_ids.add(s_id)
                raise ValueError(
                    f"List for 'steps' must contain steps with unique 'stepId's. Found duplicate IDs: {list(set(duplicate_ids))}.")
        return v

    success_actions: Optional[List[Union['SuccessAction', 'ReusableObject']]] = Field(
        None, description="A list of success actions that are applicable for all steps described under this workflow"
    )

    @field_validator('success_actions')
    @classmethod
    def validate_success_actions_uniqueness(cls, v: Optional[List[Union['SuccessAction', 'ReusableObject']]]) -> \
    Optional[List[Union['SuccessAction', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "success_actions")
        return v

    failure_actions: Optional[List[Union['FailureAction', 'ReusableObject']]] = Field(
        None, description="A list of failure actions that are applicable for all steps described under this workflow"
    )

    @field_validator('failure_actions')
    @classmethod
    def validate_failure_actions_uniqueness(cls, v: Optional[List[Union['FailureAction', 'ReusableObject']]]) -> \
    Optional[List[Union['FailureAction', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "failure_actions")
        return v

    outputs: Optional[Dict[str, str]] = Field(
        None, description="A map between a friendly name and a dynamic output value"
    )
    parameters: Optional[List[Union['Parameter', 'ReusableObject']]] = Field(
        None, description="A list of parameters that are applicable for all steps described under this workflow"
    )

    @field_validator('parameters')
    @classmethod
    def validate_workflow_parameters_uniqueness(cls, v: Optional[List[Union['Parameter', 'ReusableObject']]]) -> \
    Optional[List[Union['Parameter', 'ReusableObject']]]:
        if v is not None:
            validate_unique_items(v, "parameters")
        return v


class Components(SpecificationExtensionsMixin):
    """
    Holds a set of reusable objects for different aspects of the Arazzo Specification.
    Corresponds to #/$defs/components-object
    """
    inputs: Optional[Dict[str, Schema]] = Field(None,
                                                description="An object to hold reusable JSON Schema 2020-12 schemas to be referenced from workflow inputs")
    parameters: Optional[Dict[str, Parameter]] = Field(None, description="An object to hold reusable Parameter Objects")
    success_actions: Optional[Dict[str, SuccessAction]] = Field(None,
                                                                description="An object to hold reusable Success Actions Objects")
    failure_actions: Optional[Dict[str, FailureAction]] = Field(None,
                                                                description="An object to hold reusable Failure Actions Objects")


class ArazzoSpecification(SpecificationExtensionsMixin):
    """
    The root document for an Arazzo workflow specification.
    Corresponds to the root schema.
    """
    arazzo: str = Field(..., description="The version number of the Arazzo Specification", pattern=r"^1\.0\.\d+(-.+)?$")
    info: Info = Field(..., description="Metadata about the Arazzo description")
    source_descriptions: List[SourceDescription] = Field(
        ..., min_length=1, description="A list of source descriptions such as Arazzo or OpenAPI"
    )

    @field_validator('source_descriptions')
    @classmethod
    def validate_source_descriptions_uniqueness(cls, v: List[SourceDescription]) -> List[SourceDescription]:
        if v is not None:
            # For SourceDescription, uniqueness should be by 'name' or 'url'.
            # Assuming 'name' is the primary unique identifier for these objects.
            names = [s.name for s in v]
            if len(names) != len(set(names)):
                seen_names = set()
                duplicate_names = []
                for name in names:
                    if name in seen_names:
                        duplicate_names.append(name)
                    else:
                        seen_names.add(name)
                raise ValueError(
                    f"List for 'source_descriptions' must contain sources with unique 'name's. Found duplicate names: {list(set(duplicate_names))}.")
        return v

    workflows: List[Workflow] = Field(
        ..., min_length=1, description="A list of workflows"
    )

    @field_validator('workflows')
    @classmethod
    def validate_workflows_uniqueness(cls, v: List[Workflow]) -> List[Workflow]:
        if v is not None:
            # For Workflow objects, uniqueness should be by 'workflow_id'.
            workflow_ids = [w.workflow_id for w in v]
            if len(workflow_ids) != len(set(workflow_ids)):
                seen_ids = set()
                duplicate_ids = []
                for w_id in workflow_ids:
                    if w_id in seen_ids:
                        duplicate_ids.append(w_id)
                    else:
                        seen_ids.add(w_id)
                raise ValueError(
                    f"List for 'workflows' must contain workflows with unique 'workflowId's. Found duplicate IDs: {list(set(duplicate_ids))}.")
        return v

    components: Optional[Components] = Field(None,
                                             description="Holds a set of reusable objects for different aspects of the Arazzo Specification")


def validate_arazzo_data(data: Dict[str, Any]) -> ArazzoSpecification:
    """
    Validates a dictionary against the ArazzoSpecification model.

    Args:
        data: The dictionary representing the Arazzo specification.

    Returns:
        An instance of ArazzoSpecification if validation is successful.

    Raises:
        ValidationError: If the data does not conform to the schema.
    """
    return ArazzoSpecification.model_validate(data)


def load_and_validate_arazzo_json(json_string_or_filepath: str) -> ArazzoSpecification:
    """
    Loads and validates an Arazzo specification from a JSON string or file.

    Args:
        json_string_or_filepath: A string containing JSON data or a path to a JSON file.

    Returns:
        An instance of ArazzoSpecification if validation is successful.

    Raises:
        ValidationError: If the data does not conform to the schema.
        json.JSONDecodeError: If the string is not valid JSON.
        FileNotFoundError: If the filepath does not exist.
    """
    try:
        if Path(json_string_or_filepath).is_file() and Path(json_string_or_filepath).suffix.lower() == '.json':
            with open(json_string_or_filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = json.loads(json_string_or_filepath)
        return validate_arazzo_data(data)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading JSON: {e}")
        raise
    except ValidationError as e:
        print(f"Validation error for JSON data: {e}")
        raise


def load_and_validate_arazzo_yaml(yaml_string_or_filepath: str) -> ArazzoSpecification:
    """
    Loads and validates an Arazzo specification from a YAML string or file.

    Args:
        yaml_string_or_filepath: A string containing YAML data or a path to a YAML file.

    Returns:
        An instance of ArazzoSpecification if validation is successful.

    Raises:
        ValidationError: If the data does not conform to the schema.
        yaml.YAMLError: If the string is not valid YAML.
        FileNotFoundError: If the filepath does not exist.
        ImportError: If PyYAML is not installed.
    """

    try:
        if Path(yaml_string_or_filepath).is_file() and Path(yaml_string_or_filepath).suffix.lower() in ['.yaml',
                                                                                                        '.yml']:
            with open(yaml_string_or_filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        else:
            data = yaml.safe_load(yaml_string_or_filepath)

        return validate_arazzo_data(data)
    except (yaml.YAMLError, FileNotFoundError) as e:
        print(f"Error loading YAML: {e}")
        raise
    except ValidationError as e:
        print(f"Validation error for YAML data: {e}")
        raise
