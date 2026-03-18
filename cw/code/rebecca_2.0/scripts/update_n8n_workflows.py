#!/usr/bin/env python3
"""
Script to update n8n onboarding and offboarding workflows via API.
"""
import json
import os
import requests

N8N_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1YjI3NTRlMi0zYjU3LTQwMjMtYTYzYS0wNDBlOWQxZjg0ZTAiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwiaWF0IjoxNzY4MTM5MTM0fQ.3koy0H5mBrSf7BxZ5R11nHu6rPCsz-MNf88biV4kKZA"
N8N_URL = "http://localhost:5678"

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json"
}

# Onboarding workflow - ID: AgNm7CeITPDvS-pg7RfMI
ONBOARDING_WORKFLOW = {
    "name": "Intern Onboarding",
    "nodes": [
        {
            "parameters": {
                "httpMethod": "POST",
                "path": "onboarding",
                "responseMode": "responseNode",
                "options": {}
            },
            "id": "17b203f3-7436-4014-8fcc-a56b731a9a71",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-400, 112],
            "webhookId": "onboarding"
        },
        {
            "parameters": {
                "mode": "raw",
                "jsonOutput": "={{ { \"intern_id\": $json.body.intern_id, \"intern_name\": $json.body.intern_name, \"program\": $json.body.program, \"start_date\": $json.body.start_date, \"supervisor\": $json.body.supervisor, \"email\": $json.body.intern_email, \"github_username\": $json.body.github_username, \"zoom_meeting_ids\": $json.body.zoom_meeting_ids || [], \"execution_id\": $json.body.execution_id } }}",
                "options": {}
            },
            "id": "4730fb42-c1f7-4447-82b5-c9adec220476",
            "name": "Extract Data",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [-208, 112]
        },
        {
            "parameters": {
                "respondWith": "json",
                "responseBody": "={{ { \"status\": \"accepted\", \"execution_id\": $json.execution_id, \"message\": \"Onboarding workflow started for \" + $json.intern_name } }}",
                "options": {}
            },
            "id": "8c772cab-699c-405e-a0e2-8d95f4233f57",
            "name": "Respond to Webhook",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.1,
            "position": [0, 0]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"general\", \"message\": \"Welcome to Cloud Warriors, \" + $json.intern_name + \"!\\n\\nYou are joining the \" + $json.program + \" program. Your supervisor is \" + $json.supervisor + \".\\n\\nStart date: \" + $json.start_date + \"\\n\\nOrientation Presentation: https://docs.google.com/presentation/d/1AUYLuU5KK4jFfdDUlW41wBadSDEMC_nc/edit?usp=drive_link\" + ($json.github_username ? \"\\n\\nA GitHub org invitation has been sent to @\" + $json.github_username + \".\" : \"\") + \"\\n\\nYou will be added to the following recurring meetings:\\n- DevOps Morning Meeting (Daily 1030 EST)\\n- DevOps Change Window (Thursday)\\n- DevOps Friday Meeting\" } }}",
                "options": {}
            },
            "id": "e1768d09-96d8-47e8-b987-e475939545d6",
            "name": "Send Welcome Message",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [0, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/meetings/register",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"email\": $json.email, \"first_name\": $json.intern_name.split(\" \")[0], \"last_name\": $json.intern_name.split(\" \").slice(1).join(\" \"), \"intern_id\": $json.intern_id } }}",
                "options": {}
            },
            "id": "meeting-registration-node",
            "name": "Register for Meetings",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [208, 320],
            "continueOnFail": True
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict"
                    },
                    "conditions": [
                        {
                            "id": "github-check",
                            "leftValue": "={{ $json.github_username }}",
                            "rightValue": "",
                            "operator": {
                                "type": "string",
                                "operation": "notEmpty"
                            }
                        }
                    ],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "github-check-node",
            "name": "Has GitHub Username?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [208, 208]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/github/invite",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"username\": $(\"Extract Data\").item.json.github_username, \"intern_id\": $(\"Extract Data\").item.json.intern_id } }}",
                "options": {}
            },
            "id": "github-invite-node",
            "name": "Invite to GitHub Org",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [416, 100],
            "continueOnFail": True
        },
        {
            "parameters": {
                "unit": "days"
            },
            "id": "0cd7bd3a-a0bb-403c-b638-7e9dc31908b9",
            "name": "Wait 1 Day",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [624, 208],
            "webhookId": "e5f50b66-2fa8-4f7b-8700-60bc7e9e6358"
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"general\", \"message\": \"Hi \" + $(\"Extract Data\").item.json.intern_name + \"! Here is your Day 1 orientation checklist:\\n\\n- [ ] Review the Getting Started guide\\n- [ ] Set up your development environment\\n- [ ] Join the Daily DevOps meeting at 9 AM\\n- [ ] Introduce yourself in the team chat\\n- [ ] Review your first assigned issues\\n\\nLet me know if you have any questions!\" } }}",
                "options": {}
            },
            "id": "2ba39e5c-9afa-42ca-aa85-b2e4ea1b66f9",
            "name": "Send Orientation Checklist",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [832, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "unit": "days",
                "amount": 4
            },
            "id": "b42f2033-de02-40a7-a8ae-70f9ef9c4dc7",
            "name": "Wait Until Friday",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [1040, 208],
            "webhookId": "629a37cc-501b-4e49-9952-945064993eef"
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"general\", \"message\": \"Week 1 check-in for \" + $(\"Extract Data\").item.json.intern_name + \":\\n\\nHow is your first week going? Please share:\\n- What you have accomplished\\n- Any blockers or questions\\n- Topics you would like to learn more about\\n\\n\" + $(\"Extract Data\").item.json.supervisor + \" will review your progress.\" } }}",
                "options": {}
            },
            "id": "96225a66-140f-47ce-88db-4c01c936d4f5",
            "name": "Week 1 Check-in",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1248, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/n8n/callback",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"execution_id\": $(\"Extract Data\").item.json.execution_id, \"status\": \"completed\", \"secret\": $env.N8N_CALLBACK_SECRET, \"result\": { \"intern_name\": $(\"Extract Data\").item.json.intern_name, \"github_username\": $(\"Extract Data\").item.json.github_username, \"steps_completed\": [\"welcome\", \"github_invite\", \"checklist\", \"week1_checkin\"] } } }}",
                "options": {}
            },
            "id": "2b3c140f-363b-4e18-bda8-e5ac4e724958",
            "name": "Notify QA Bot Complete",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1456, 208],
            "continueOnFail": True
        }
    ],
    "connections": {
        "Webhook": {
            "main": [[{"node": "Extract Data", "type": "main", "index": 0}]]
        },
        "Extract Data": {
            "main": [
                [
                    {"node": "Respond to Webhook", "type": "main", "index": 0},
                    {"node": "Send Welcome Message", "type": "main", "index": 0},
                    {"node": "Register for Meetings", "type": "main", "index": 0}
                ]
            ]
        },
        "Send Welcome Message": {
            "main": [[{"node": "Has GitHub Username?", "type": "main", "index": 0}]]
        },
        "Has GitHub Username?": {
            "main": [
                [{"node": "Invite to GitHub Org", "type": "main", "index": 0}],
                [{"node": "Wait 1 Day", "type": "main", "index": 0}]
            ]
        },
        "Invite to GitHub Org": {
            "main": [[{"node": "Wait 1 Day", "type": "main", "index": 0}]]
        },
        "Wait 1 Day": {
            "main": [[{"node": "Send Orientation Checklist", "type": "main", "index": 0}]]
        },
        "Send Orientation Checklist": {
            "main": [[{"node": "Wait Until Friday", "type": "main", "index": 0}]]
        },
        "Wait Until Friday": {
            "main": [[{"node": "Week 1 Check-in", "type": "main", "index": 0}]]
        },
        "Week 1 Check-in": {
            "main": [[{"node": "Notify QA Bot Complete", "type": "main", "index": 0}]]
        }
    },
    "settings": {
        "executionOrder": "v1"
    }
}

# Offboarding workflow - ID: WJW6LYnDvWGoBmyBar49-
OFFBOARDING_WORKFLOW = {
    "name": "Intern Offboarding",
    "nodes": [
        {
            "parameters": {
                "httpMethod": "POST",
                "path": "offboarding",
                "responseMode": "responseNode",
                "options": {}
            },
            "id": "15199064-634f-4fff-8795-c04a10f34cfb",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-400, 112],
            "webhookId": "offboarding"
        },
        {
            "parameters": {
                "mode": "raw",
                "jsonOutput": "={{ { \"intern_id\": $json.body.intern_id, \"intern_name\": $json.body.intern_name, \"email\": $json.body.intern_email, \"github_username\": $json.body.github_username, \"exit_survey_url\": $json.body.exit_survey_url, \"end_date\": $json.body.end_date, \"reason\": $json.body.reason, \"execution_id\": $json.body.execution_id } }}",
                "options": {}
            },
            "id": "33477101-19c7-497d-809e-e4be73da116a",
            "name": "Extract Data",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [-208, 112]
        },
        {
            "parameters": {
                "respondWith": "json",
                "responseBody": "={{ { \"status\": \"accepted\", \"execution_id\": $json.execution_id, \"message\": \"Offboarding workflow started for \" + $json.intern_name } }}",
                "options": {}
            },
            "id": "679966a6-3aaa-453d-9cbd-60e6ac8d3645",
            "name": "Respond to Webhook",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.1,
            "position": [0, 0]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"general\", \"message\": \"Offboarding initiated for \" + $json.intern_name + \" (end date: \" + $json.end_date + \").\\n\\nOffboarding checklist:\\n- [ ] Complete any in-progress tasks or hand off\\n- [ ] Document any work in progress\\n- [ ] Return any equipment\\n- [ ] Complete exit interview\" + ($json.exit_survey_url ? \"\\n\\nPlease complete the exit survey: \" + $json.exit_survey_url : \"\") } }}",
                "options": {}
            },
            "id": "d896ff0b-ef01-4512-99a5-33c184b0980a",
            "name": "Send Offboarding Checklist",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [0, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict"
                    },
                    "conditions": [
                        {
                            "id": "github-check",
                            "leftValue": "={{ $json.github_username }}",
                            "rightValue": "",
                            "operator": {
                                "type": "string",
                                "operation": "notEmpty"
                            }
                        }
                    ],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "github-offboard-check",
            "name": "Has GitHub Username?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [208, 208]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/github/remove",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"username\": $(\"Extract Data\").item.json.github_username, \"intern_id\": $(\"Extract Data\").item.json.intern_id } }}",
                "options": {}
            },
            "id": "github-remove-node",
            "name": "Remove from GitHub Org",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [416, 100],
            "continueOnFail": True
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"devops\", \"message\": \"IT Action Required: Please schedule access revocation for \" + $(\"Extract Data\").item.json.intern_name + \" effective \" + $(\"Extract Data\").item.json.end_date + \".\\n\\nSystems to review:\\n- GitHub organization access\" + ($(\"Extract Data\").item.json.github_username ? \" (@\" + $(\"Extract Data\").item.json.github_username + \" - removal initiated)\" : \"\") + \"\\n- Cloud platform access\\n- Internal tools and dashboards\" } }}",
                "options": {}
            },
            "id": "404745ff-f62e-449b-99b3-690925c52c3c",
            "name": "Notify IT for Access Revocation",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [624, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "unit": "days"
            },
            "id": "14c33833-85b4-4384-b7ec-2592ae843911",
            "name": "Wait Until End Date",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [832, 208],
            "webhookId": "79f875ff-0886-4a5c-a249-dea1c52ad1ec"
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/api/zoom/send",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"channel\": \"general\", \"message\": \"Today is \" + $(\"Extract Data\").item.json.intern_name + \"'s last day with us!\\n\\nThank you for all your contributions to the team. We wish you the best in your future endeavors!\\n\\nPlease reach out if you'd like to stay connected with the Cloud Warriors alumni network.\" } }}",
                "options": {}
            },
            "id": "b2c9dc08-41b5-48a1-b6cf-535008a4aa95",
            "name": "Send Farewell Message",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1040, 208],
            "continueOnFail": True
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.QA_BOT_URL }}/n8n/callback",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ { \"execution_id\": $(\"Extract Data\").item.json.execution_id, \"status\": \"completed\", \"secret\": $env.N8N_CALLBACK_SECRET, \"result\": { \"intern_name\": $(\"Extract Data\").item.json.intern_name, \"github_username\": $(\"Extract Data\").item.json.github_username, \"end_date\": $(\"Extract Data\").item.json.end_date, \"steps_completed\": [\"checklist\", \"github_removal\", \"it_notification\", \"farewell\"] } } }}",
                "options": {}
            },
            "id": "fc9c49e4-40ad-4787-83ca-591c462801ec",
            "name": "Notify QA Bot Complete",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1248, 208],
            "continueOnFail": True
        }
    ],
    "connections": {
        "Webhook": {
            "main": [[{"node": "Extract Data", "type": "main", "index": 0}]]
        },
        "Extract Data": {
            "main": [
                [
                    {"node": "Respond to Webhook", "type": "main", "index": 0},
                    {"node": "Send Offboarding Checklist", "type": "main", "index": 0}
                ]
            ]
        },
        "Send Offboarding Checklist": {
            "main": [[{"node": "Has GitHub Username?", "type": "main", "index": 0}]]
        },
        "Has GitHub Username?": {
            "main": [
                [{"node": "Remove from GitHub Org", "type": "main", "index": 0}],
                [{"node": "Notify IT for Access Revocation", "type": "main", "index": 0}]
            ]
        },
        "Remove from GitHub Org": {
            "main": [[{"node": "Notify IT for Access Revocation", "type": "main", "index": 0}]]
        },
        "Notify IT for Access Revocation": {
            "main": [[{"node": "Wait Until End Date", "type": "main", "index": 0}]]
        },
        "Wait Until End Date": {
            "main": [[{"node": "Send Farewell Message", "type": "main", "index": 0}]]
        },
        "Send Farewell Message": {
            "main": [[{"node": "Notify QA Bot Complete", "type": "main", "index": 0}]]
        }
    },
    "settings": {
        "executionOrder": "v1"
    }
}


def update_workflow(workflow_id: str, workflow_data: dict) -> dict:
    """Update an n8n workflow via API."""
    # Remove read-only fields
    data = {k: v for k, v in workflow_data.items() if k not in ['active', 'id', 'createdAt', 'updatedAt']}

    url = f"{N8N_URL}/api/v1/workflows/{workflow_id}"
    response = requests.put(url, headers=HEADERS, json=data)

    if response.status_code != 200:
        print(f"   API Error: {response.text}")

    response.raise_for_status()
    return response.json()


def main():
    print("Updating n8n workflows...")

    # Update onboarding workflow
    print("\n1. Updating Intern Onboarding workflow...")
    try:
        result = update_workflow("AgNm7CeITPDvS-pg7RfMI", ONBOARDING_WORKFLOW)
        print(f"   Success! Workflow ID: {result.get('id')}")
        print(f"   Name: {result.get('name')}")
        print(f"   Active: {result.get('active')}")
    except Exception as e:
        print(f"   Error: {e}")

    # Update offboarding workflow
    print("\n2. Updating Intern Offboarding workflow...")
    try:
        result = update_workflow("WJW6LYnDvWGoBmyBar49-", OFFBOARDING_WORKFLOW)
        print(f"   Success! Workflow ID: {result.get('id')}")
        print(f"   Name: {result.get('name')}")
        print(f"   Active: {result.get('active')}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
