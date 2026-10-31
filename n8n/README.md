# n8n workflow (build this in the n8n UI, then export it into this folder)

1. **Webhook** node (POST). Copy its *production* URL into `N8N_WEBHOOK_URL` in `.env`.
   Body from FastAPI: `order_id, supplier, whatsapp_number, item, quantity, unit, total, message, callback_url_path`.
2. **Twilio** node (WhatsApp sandbox) or WhatsApp Cloud API node. Send `{{$json.body.message}}` to `{{$json.body.whatsapp_number}}`.
   Turn on *Retry On Fail* (3 tries) for this node.
3. **HTTP Request** node, success path: `POST http://host.docker.internal:8000/orders/{{$json.body.order_id}}/executed`
   with header `X-Webhook-Secret: <N8N_CALLBACK_SECRET>` and JSON body `{"success": true, "message_id": "{{ <twilio sid> }}"}`.
4. Same HTTP Request on the error path with `{"success": false, "error": "<message>"}`.

If `N8N_WEBHOOK_URL` is empty, FastAPI skips n8n and simulates the send.
