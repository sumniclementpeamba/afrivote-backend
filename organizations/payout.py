import requests
from django.conf import settings

PAYSTACK_BASE = 'https://api.paystack.co'

def create_transfer_recipient(recipient_type, name, account_number, bank_code):
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'type': 'mobile_money' if recipient_type == 'momo' else 'nuban',
        'name': name,
        'account_number': account_number,
        'bank_code': bank_code,
        'currency': 'GHS'
    }
    response = requests.post(f'{PAYSTACK_BASE}/transferrecipient', json=payload, headers=headers)
    data = response.json()
    if data.get('status'):
        return data['data']['recipient_code']
    raise Exception(data.get('message', 'Failed to create recipient'))

def initiate_transfer(amount, recipient_code, reason):
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'source': 'balance',
        'amount': int(float(amount) * 100),  # convert to pesewas
        'recipient': recipient_code,
        'currency': 'GHS',
        'reason': reason
    }
    response = requests.post(f'{PAYSTACK_BASE}/transfer', json=payload, headers=headers)
    data = response.json()
    if data.get('status'):
        return data['data']
    raise Exception(data.get('message', 'Transfer failed'))