import os

from pydantic import ValidationError

from models.arazzo import validate_arazzo_data, load_and_validate_arazzo_yaml

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

EXAMPLE_FILES_DIR = os.path.join(SCRIPT_DIR, "examples")

if __name__ == "__main__":

    example_files = os.listdir(EXAMPLE_FILES_DIR)

    for example_file in example_files:
        example_file_path = os.path.join(EXAMPLE_FILES_DIR, example_file)

        # Test against example from arazzo themselves
        try:
            print(f"--- Arazzo Example Validation ({example_file}) ---")
            arazzo_example = load_and_validate_arazzo_yaml(example_file_path)
            print(f"Arazzo Example Validation ({example_file}) Successful!")
        except Exception as ex:
            print(f"Arazzo Example Validation ({example_file}) Failed: {ex}")

        print("\n" + "=" * 80 + "\n")

    # Example Valid Arazzo Specification
    valid_arazzo_data = {
        "arazzo": "1.0.0",
        "info": {
            "title": "Example Arazzo Document",
            "version": "1.0.0",
            "summary": "This is a summary of the document."
        },
        "sourceDescriptions": [
            {
                "name": "petstore",
                "url": "https://petstore.swagger.io/v2/swagger.json",
                "type": "openapi"
            },
            {
                "name": "users",
                "url": "/local/arazzo/users.json",
                "type": "arazzo"
            }
        ],
        "workflows": [
            {
                "workflowId": "createPetWorkflow",
                "summary": "Workflow to add a new pet to the store.",
                "inputs": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "tag": {"type": "string"}
                    },
                    "required": ["name"]
                },
                "steps": [
                    {
                        "stepId": "addPet",
                        "description": "Call to add a pet operation",
                        "operationId": "addPet",
                        "parameters": [
                            {
                                "name": "petName",
                                # Note: `in` is not required for a parameter when it's part of `requestBody`
                                # or if it's a generic value not tied to a specific HTTP location.
                                # The Arazzo schema for `parameter-object` has `in` as optional for `workflowId` steps.
                                # For `operationId`/`operationPath` steps, `in` is required on the Parameter object.
                                # This example is intentionally simplified.
                                "value": "$.inputs.name"
                            }
                        ],
                        "successCriteria": [
                            {"condition": "$.response.statusCode == 200"}
                        ],
                        "onSuccess": [
                            {"name": "logSuccess", "type": "end"}
                        ]
                    },
                    {
                        "stepId": "getPetById",
                        "description": "Call to get pet operation",
                        "operationPath": "petstore#/paths/~1pet~1{petId}/get",
                        "parameters": [
                            {
                                "name": "petId",
                                "in": "path",
                                # This 'in' is now correctly mapped and required by validator for operation types
                                "value": "$.steps.addPet.outputs.id"  # Example of dynamic value
                            }
                        ],
                        "successCriteria": [
                            {"context": "$.response.body", "condition": "name == 'Buddy'",
                             "type": {"type": "jsonpath", "version": "draft-goessner-dispatch-jsonpath-00"}}
                            # Corrected type format
                        ]
                    }
                ],
                "outputs": {
                    "petId": "$.steps.addPet.outputs.id"
                }
            },
            {
                "workflowId": "userProfileFlow",
                "summary": "Workflow to fetch a user profile.",
                "steps": [
                    {
                        "stepId": "getUser",
                        "workflowId": "getUserDetailsWorkflow"  # Referencing another Arazzo workflow
                    },
                    {
                        "stepId": "updateUser",
                        "workflowId": "updateUserDetailsWorkflow",
                        "parameters": [
                            {"name": "userId", "value": "123"},
                            {"reference": "#/components/parameters/emailParam", "value": "new@example.com"}
                        ]
                    }
                ]
            }
        ],
        "components": {
            "parameters": {
                "emailParam": {
                    "name": "email",
                    "in": "query",
                    "value": "default@example.com"
                }
            },
            "successActions": {
                "logSuccess": {
                    "name": "logSuccess",
                    "type": "end"
                }
            }
        },
        "x-custom-extension": "some-value"
    }

    print("--- Valid Arazzo Data Validation ---")
    try:
        arazzo_spec = validate_arazzo_data(valid_arazzo_data)
        print("Validation successful!")
        print(f"Arazzo Version: {arazzo_spec.arazzo}")
        print(f"Info Title: {arazzo_spec.info.title}")
        print(f"Number of Source Descriptions: {len(arazzo_spec.source_descriptions)}")
        print(f"Number of Workflows: {len(arazzo_spec.workflows)}")
        print(f"First Workflow ID: {arazzo_spec.workflows[0].workflow_id}")
        print(f"First Step ID in first workflow: {arazzo_spec.workflows[0].steps[0].step_id}")
        if arazzo_spec.components and arazzo_spec.components.parameters:
            print(f"Component Parameter: {arazzo_spec.components.parameters['emailParam'].name}")
        if arazzo_spec.model_extra:
            print(
                f"X-Extension: {arazzo_spec.model_extra.get('x_custom_extension')}")
        print("\n" + "=" * 80 + "\n")
    except ValidationError as e:
        print("Validation failed for valid data (this should not happen):")
        print(e)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Example Invalid Arazzo Specification (missing required field) ---
    invalid_data_missing_info_version = {
        "arazzo": "1.0.0",
        "info": {
            "title": "Invalid Arazzo Doc",
            # "version": "1.0.0" # Missing required version
        },
        "sourceDescriptions": [
            {"name": "api", "url": "http://api.example.com"}
        ],
        "workflows": [
            {"workflowId": "simple", "steps": [{"stepId": "s1", "operationId": "op1"}]}
        ]
    }

    print("--- Invalid Arazzo Data Validation (Missing Info Version) ---")
    try:
        _ = validate_arazzo_data(invalid_data_missing_info_version)
        print("Validation unexpectedly successful for invalid data.")
    except ValidationError as e:
        print("Validation failed as expected for invalid data (missing info.version):")
        print(e.errors())
        print("\n" + "=" * 80 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Example Invalid Step (missing operation/workflow target) ---
    invalid_step_data = {
        "arazzo": "1.0.0",
        "info": {"title": "Invalid Step Test", "version": "1.0.0"},
        "sourceDescriptions": [
            {"name": "api", "url": "http://api.example.com"}
        ],
        "workflows": [
            {
                "workflowId": "broken_step",
                "steps": [
                    {
                        "stepId": "s1",
                        # Missing operationId, operationPath, or workflowId
                    }
                ]
            }
        ]
    }
    print("--- Invalid Arazzo Data Validation (Invalid Step) ---")
    try:
        _ = validate_arazzo_data(invalid_step_data)
        print("Validation unexpectedly successful for invalid step.")
    except ValidationError as e:
        print("Validation failed as expected for invalid step:")
        print(e.errors())
        print("\n" + "=" * 80 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Example Invalid Step (operation-based parameter missing 'in') ---
    invalid_step_param_data = {
        "arazzo": "1.0.0",
        "info": {"title": "Invalid Step Param Test", "version": "1.0.0"},
        "sourceDescriptions": [
            {"name": "api", "url": "http://api.example.com"}
        ],
        "workflows": [
            {
                "workflowId": "broken_param_step",
                "steps": [
                    {
                        "stepId": "s1",
                        "operationId": "getSomething",
                        "parameters": [
                            {"name": "myParam", "value": "abc"}  # Missing 'in' field for operation-based step
                        ]
                    }
                ]
            }
        ]
    }
    print("--- Invalid Arazzo Data Validation (Operation Param Missing 'in') ---")
    try:
        _ = validate_arazzo_data(invalid_step_param_data)
        print("Validation unexpectedly successful for invalid step parameter.")
    except ValidationError as e:
        print("Validation failed as expected for invalid step parameter:")
        print(e.errors())
        print("\n" + "=" * 80 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Example Invalid Data (Duplicate WorkflowId) ---
    invalid_duplicate_workflow_id = {
        "arazzo": "1.0.0",
        "info": {"title": "Duplicate Workflow Test", "version": "1.0.0"},
        "sourceDescriptions": [{"name": "api", "url": "http://api.example.com"}],
        "workflows": [
            {"workflowId": "workflow1", "steps": [{"stepId": "s1", "operationId": "op1"}]},
            {"workflowId": "workflow1", "steps": [{"stepId": "s2", "operationId": "op2"}]}
        ]
    }
    print("--- Invalid Arazzo Data Validation (Duplicate WorkflowId) ---")
    try:
        _ = validate_arazzo_data(invalid_duplicate_workflow_id)
        print("Validation unexpectedly successful for duplicate workflow ID.")
    except ValidationError as e:
        print("Validation failed as expected for duplicate workflow ID:")
        print(e.errors())
        print("\n" + "=" * 80 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Example Invalid Data (Duplicate StepId within a workflow) ---
    invalid_duplicate_step_id = {
        "arazzo": "1.0.0",
        "info": {"title": "Duplicate Step Test", "version": "1.0.0"},
        "sourceDescriptions": [{"name": "api", "url": "http://api.example.com"}],
        "workflows": [
            {
                "workflowId": "workflow_with_dup_steps",
                "steps": [
                    {"stepId": "stepA", "operationId": "opA"},
                    {"stepId": "stepA", "operationId": "opB"}  # Duplicate stepId
                ]
            }
        ]
    }
    print("--- Invalid Arazzo Data Validation (Duplicate StepId within Workflow) ---")
    try:
        _ = validate_arazzo_data(invalid_duplicate_step_id)
        print("Validation unexpectedly successful for duplicate step ID.")
    except ValidationError as e:
        print("Validation failed as expected for duplicate step ID:")
        print(e.errors())
        print("\n" + "=" * 80 + "\n")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
