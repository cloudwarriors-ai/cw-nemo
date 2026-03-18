# n8n Setup for QA Continuity App

This directory contains the Docker configuration for running n8n locally.

## Quick Start

### 1. Prerequisites
- Docker Desktop installed and running
- Port 5678 available

### 2. Configure Environment

```bash
cd n8n
copy .env.example .env
```

Edit `.env` and set secure values:
- `N8N_ENCRYPTION_KEY`: Generate with `openssl rand -hex 16` or use a random 32-character string
- `N8N_PASSWORD`: Strong password for the n8n UI

### 3. Start n8n

```bash
docker-compose up -d
```

### 4. Access n8n UI

Open http://localhost:5678

Login with:
- Username: `admin` (or your `N8N_USER`)
- Password: Your `N8N_PASSWORD`

## Workflow Setup

After n8n is running, import the workflows:

### Onboarding Workflow
1. Create new workflow
2. Add **Webhook** node (trigger)
   - HTTP Method: POST
   - Path: `onboarding`
   - Copy the **Production URL** (e.g., `http://localhost:5678/webhook/onboarding`)
3. Add workflow steps (see below)
4. Activate the workflow

### Offboarding Workflow
1. Create new workflow
2. Add **Webhook** node with path: `offboarding`
3. Add workflow steps
4. Activate

### Weekly Feedback Workflow
1. Create new workflow
2. Add **Webhook** node with path: `weekly-feedback`
3. Add workflow steps
4. Activate

### Report Upload Workflow (Google Drive)
This workflow receives an Excel file (base64 encoded) and uploads it to Google Drive.

**Nodes: Webhook → Convert to File → Google Drive**

1. Create new workflow
2. Add **Webhook** node:
   - HTTP Method: POST
   - Path: `report-upload`
   - Response Mode: **Last Node** (synchronous - we need the Drive link)
3. Add **Convert to File** node:
   - Operation: **Move Base64 String to File**
   - Source Property (INPUT FIELD NAME): `body.file_base64` (plain text, NOT an expression)
   - MIME Type: Leave blank (auto-detected)
   - File Name: Switch to **Expression** mode, enter: `{{ $json.body.filename }}`
   - Put Output File in Field: `data`
4. Add **Google Drive** node:
   - Credential: Your Google Drive OAuth2 credential
   - Resource: File
   - Operation: Upload
   - Input Data Field Name: `data` (plain text, NOT an expression)
   - Drive: Select your shared drive or "My Drive"
   - Folder: Select your reports folder (e.g., DevOps)
   - File Name: Switch to **Expression** mode, enter: `{{ $('Webhook').item.json.body.filename }}`
5. Activate the workflow

**IMPORTANT:** The file name in the Google Drive node must use `{{ $('Webhook').item.json.body.filename }}`
to get the filename from the original webhook payload. Using just `{{ $json.filename }}` won't work
because the Convert to File node changes the structure.

**Testing:** The workflow returns the Google Drive response including `webViewLink` which is the shareable URL.

## Connecting to QA Bot

Once workflows are created, update the main app's `.env`:

```bash
N8N_WEBHOOK_URL=http://localhost:5678/webhook
N8N_CALLBACK_SECRET=your-secure-random-secret
```

## Workflow Node Examples

### Onboarding Workflow Nodes:

```
[Webhook] → [Set Variables] → [Send Zoom Message] → [Create Google Doc] → [Wait 1 day] → [Send Checklist]
```

**Node 1: Webhook (Trigger)**
- Path: `onboarding`
- Response Mode: "Last Node"

**Node 2: Set Variables**
- Extract `intern_name`, `intern_id`, `program`, `start_date` from webhook body

**Node 3: Send Zoom Message (HTTP Request)**
- Method: POST
- URL: Your Zoom webhook URL
- Body: Welcome message with intern details

**Node 4: Create Google Doc (Google Docs node)**
- Use template document
- Replace placeholders with intern details

**Node 5: Wait**
- Wait 1 day

**Node 6: Send Checklist (HTTP Request)**
- Send orientation checklist to Zoom

### Callback to QA Bot

At the end of each workflow, add an HTTP Request node to notify completion:

```
URL: http://your-qa-bot/n8n/callback
Method: POST
Body:
{
  "execution_id": "{{ $json.execution_id }}",
  "status": "completed",
  "secret": "your-callback-secret"
}
```

## Production Deployment

For production, consider:

1. **Use a domain** with HTTPS (nginx reverse proxy + Let's Encrypt)
2. **Secure the webhook URLs** (add authentication headers)
3. **Backup the data volume** regularly
4. **Monitor execution logs**

### Production docker-compose override:

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  n8n:
    environment:
      - N8N_HOST=n8n.yourdomain.com
      - N8N_PROTOCOL=https
      - WEBHOOK_URL=https://n8n.yourdomain.com/
```

Run with: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

## Troubleshooting

### n8n won't start
```bash
docker-compose logs n8n
```

### Webhook not receiving requests
- Ensure workflow is **activated** (toggle in top right)
- Use the **Production URL**, not Test URL
- Check firewall/port forwarding

### Credentials issues
- Regenerate encryption key
- Delete volume and restart: `docker-compose down -v && docker-compose up -d`

## Useful Commands

```bash
# View logs
docker-compose logs -f n8n

# Restart
docker-compose restart

# Stop
docker-compose down

# Stop and remove data
docker-compose down -v

# Update n8n
docker-compose pull && docker-compose up -d
```
