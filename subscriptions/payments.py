import requests
from django.conf import settings
from django.utils import timezone

PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = 'https://api.paystack.co'

def create_payment_link(organization, amount, target_plan, currency='GHS',
                        redirect_url='http://localhost:3000/dashboard/billing'):
    """
    Initialize a Paystack transaction and return the authorization URL.
    `target_plan` is the plan the organisation wants to upgrade to (e.g., 'STANDARD').
    """
    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    tx_ref = f"org-{organization.id}-{int(timezone.now().timestamp())}"
    data = {
        "email": organization.email,
        "amount": int(amount * 100),
        "currency": currency,
        "reference": tx_ref,
        # The callback URL now includes the target plan, not the current plan
        "callback_url": f"{redirect_url}?reference={tx_ref}&plan={target_plan}",
        "metadata": {
            "organization_id": str(organization.id),
            "plan": target_plan,          # also store in metadata
        }
    }

    try:
        response = requests.post(
            f'{PAYSTACK_BASE_URL}/transaction/initialize',
            json=data,
            headers=headers,
            timeout=15
        )
        if response.status_code == 200:
            resp_data = response.json()
            if resp_data.get('status'):
                return resp_data['data']['authorization_url']
    except requests.RequestException as e:
        print(f"Paystack initialize error: {e}")
    return None


def verify_payment(reference):
    """Verify a Paystack transaction by reference."""
    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
    }
    try:
        response = requests.get(
            f'{PAYSTACK_BASE_URL}/transaction/verify/{reference}',
            headers=headers,
            timeout=15
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException as e:
        print(f"Paystack verify error: {e}")
    return None