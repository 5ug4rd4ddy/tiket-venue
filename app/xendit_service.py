import xendit
import os
from xendit.apis import InvoiceApi
from xendit.invoice.model.create_invoice_request import CreateInvoiceRequest
from .models import SiteSetting

class XenditService:
    def __init__(self, secret_key=None):
        if not secret_key:
            settings = SiteSetting.query.first()
            if settings and settings.xendit_secret_key:
                self.secret_key = settings.xendit_secret_key
            else:
                self.secret_key = os.getenv('XENDIT_SECRET_KEY')
        else:
            self.secret_key = secret_key
        
        if self.secret_key:
            xendit.set_api_key(self.secret_key)
            self.api_client = xendit.ApiClient()
            self.invoice_api = InvoiceApi(self.api_client)
        else:
            self.api_client = None
            self.invoice_api = None

    def create_invoice(self, obj, success_redirect_url, failure_redirect_url, payment_methods=None):
        if not self.invoice_api:
            raise Exception("Xendit Secret Key belum dikonfigurasi di pengaturan.")

        # Determine if obj is Order or DepositTransaction
        is_order = hasattr(obj, 'invoice_number')
        
        external_id = obj.invoice_number if is_order else obj.external_id
        amount = float(obj.total_price) if is_order else float(obj.amount)
        
        # Determine customer info
        if is_order:
            customer_name = obj.customer_name
            customer_email = obj.customer_email
            customer_phone = obj.customer_phone
            description = f"Tiket Wahana - {external_id}"
        else:
            # For deposit topup, we get info from user
            customer_name = obj.user.name
            customer_email = obj.user.email
            customer_phone = obj.user.phone
            description = f"Deposit Reseller - {external_id}"

        # Create the request object as required by SDK v7
        invoice_params = {
            "external_id": external_id,
            "amount": amount,
            "payer_email": customer_email,
            "description": description,
            "customer": {
                "given_names": customer_name,
                "email": customer_email,
                "mobile_number": customer_phone
            },
            "success_redirect_url": success_redirect_url,
            "failure_redirect_url": failure_redirect_url
        }

        if payment_methods:
            invoice_params["payment_methods"] = payment_methods

        invoice_request = CreateInvoiceRequest(**invoice_params)

        try:
            created_invoice = self.invoice_api.create_invoice(invoice_request)
            return created_invoice
        except xendit.XenditSdkException as e:
            print(f"Xendit SDK Error: {e}")
            raise e
        except Exception as e:
            print(f"Xendit General Error: {e}")
            raise e
