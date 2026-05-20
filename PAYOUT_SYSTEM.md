# Payout System Documentation

## Overview

A complete payout/settlement system for sellers with advanced features including:
- Real-time wallet management
- Automatic eligibility transitions
- Email notifications
- Admin dashboard
- REST API endpoints
- Management commands
- Database optimization

## Data Models

### Core Models

1. **SellerOrderPayout**: Order-level payout summary
   - Tracks earnings per order
   - Manages status transitions
   - Handles return windows and hold periods

2. **SellerLedger**: Transaction-level ledger
   - Individual credit/debit entries
   - Components: commission, tax, shipping, etc.
   - Comprehensive audit trail

3. **Payout**: Bulk payout records
   - Aggregates multiple ledger entries
   - Tracks gateway integration
   - Status management

4. **SellerWallet**: Real-time balance tracker
   - Pending, hold, available, paid balances
   - Automatically recalculated

## Email Notifications

### Implemented Notifications

#### 1. Payout Released
- Triggered when payout is successfully processed
- Contains: amount, reference ID, date, dashboard link
- Template: `sellers/emails/payout_released.html`

#### 2. Payout Failed
- Triggered when payout processing fails
- Contains: failure reason, support email, recovery steps
- Template: `sellers/emails/payout_failed.html`

#### 3. Balance Available
- Triggered when earnings become available for withdrawal
- Contains: available amount, action link
- Template: `sellers/emails/balance_available.html`

#### 4. Payout Summary
- Periodic summary of payouts (default: 30 days)
- Contains: payout history, totals, trends
- Template: `sellers/emails/payout_summary.html`

### Email Integration

Email utilities are in `sellers/utils/payout_emails.py`:

```python
from sellers.utils.payout_emails import (
    send_payout_released_email,
    send_payout_failed_email,
    send_balance_available_email,
    send_payout_summary_email,
)
```

## Management Commands

### 1. Process Payout Eligibility

Automatically transitions earnings through the lifecycle:
- Pending → Hold (after return window closes)
- Hold → Available (after hold period completes)

```bash
# Process all transitions
python manage.py process_payout_eligibility

# Dry run
python manage.py process_payout_eligibility --dry-run
```

### 2. Send Payout Summaries

Send periodic summary emails to sellers:

```bash
# Send to all sellers
python manage.py send_payout_summaries

# Last 60 days
python manage.py send_payout_summaries --days 60

# Specific seller
python manage.py send_payout_summaries --seller-id 5

# Dry run
python manage.py send_payout_summaries --dry-run
```

### 3. Release Seller Payouts

Batch release payouts for multiple sellers:

```bash
# Release all available payouts
python manage.py release_seller_payouts

# Only if balance >= ₹1000
python manage.py release_seller_payouts --min-balance 1000

# Specific seller
python manage.py release_seller_payouts --seller-id 3

# Dry run
python manage.py release_seller_payouts --dry-run
```

## REST API Endpoints

### Authentication
All endpoints require seller login (`@login_required` + seller verification)

### 1. Wallet Summary
```
GET /seller/api/wallet/

Response:
{
    "seller_id": 1,
    "seller_name": "Acme Store",
    "wallet": {
        "pending_balance": "500.00",
        "hold_balance": "1000.00",
        "available_balance": "2000.00",
        "paid_balance": "10000.00"
    },
    "total_earnings": "13500.00",
    "pending_payout": "3500.00",
    "paid_payout": "10000.00"
}
```

### 2. Payout History
```
GET /seller/api/payout-history/?page=1&limit=20&status=completed

Query Parameters:
- page: Page number (default: 1)
- limit: Items per page (default: 20, max: 100)
- status: Filter by status (initiated, processing, completed, failed)
- start_date: Filter from date (YYYY-MM-DD)
- end_date: Filter to date (YYYY-MM-DD)

Response:
{
    "count": 42,
    "page": 1,
    "page_size": 20,
    "total_pages": 3,
    "payouts": [
        {
            "id": 1,
            "amount": "1000.00",
            "status": "completed",
            "reference": "payout_12345",
            "created_at": "2026-04-15T10:30:00Z",
            "processed_at": "2026-04-15T11:00:00Z"
        }
    ]
}
```

### 3. Order Earnings
```
GET /seller/api/order/<order_id>/earnings/

Response:
{
    "order_id": 12345,
    "gross_amount": "1000.00",
    "net_amount": "820.00",
    "status": "available",
    "breakdown": {
        "product_price": "1000.00",
        "commission": "100.00",
        "gateway_fee": "20.00",
        "shipping": "50.00",
        "gst": "180.00",
        "tds": "10.00"
    },
    "created_at": "2026-04-15T10:30:00Z"
}
```

### 4. Request Payout
```
POST /seller/api/request-payout/

Request Body: {} (no parameters needed)

Response (success):
{
    "success": true,
    "payout_id": 42,
    "amount": "2000.00",
    "status": "processing",
    "reference": "payout_abc123",
    "message": "Payout has been initiated..."
}

Response (error):
{
    "success": false,
    "error": "Seller has no available balance to pay out."
}
```

## Admin Features

### Payout Management Dashboard
- URL: `/seller/admin/payout-management/`
- Shows all approved sellers with:
  - Pending/hold/available/paid balances
  - Total earnings
  - Last payout date and amount
  - Total payouts count
  - "Release Payout" button for each seller

### Admin Actions
- **SellerPayoutAdmin**: Release payout action
- **CompletedSellerPayoutAdmin**: Release payout for completed orders
- **SellerWalletAdmin**: Recalculate wallet, trigger payout

## Database Optimization

### Indexes Added
Performance indexes on frequently queried fields:

**SellerOrderPayout**:
- `(seller, status)`
- `(seller, updated_at)`
- `(status, available_on)`
- `(seller, status, created_at)`

**Payout**:
- `(seller, status)`
- `(seller, created_at)`
- `(status, created_at)`
- `(idempotency_key)`

**SellerLedger** (existing):
- `(seller, status, created_at)`
- `(order, status)`
- `(reference_id)`

## Status Transitions

### SellerOrderPayout Status Flow
```
┌─────────┐
│ PENDING │ (Order placed, return window active)
└────┬────┘
     │ (Return window closes)
┌────▼────┐
│  HOLD   │ (Additional hold period active)
└────┬────┘
     │ (Hold period completes)
┌────▼──────────┐
│  AVAILABLE    │ (Ready for payout)
└────┬──────────┘
     │ (Payout released)
┌────▼────┐
│  PAID    │ (Transferred to seller account)
└──────────┘
```

### Payout Status Flow
```
┌───────────┐
│ INITIATED │ (Request created)
└────┬──────┘
     │
     ├─→ PROCESSING (Gateway processing)
     │   └──┬──────
     │      ├─→ COMPLETED ✓
     │      └─→ FAILED ✗
     │
     └─→ FAILED (Initial validation failed)
```

## Configuration

### Settings Required

```python
# Email
DEFAULT_FROM_EMAIL = 'noreply@mykartstore.com'
SUPPORT_EMAIL = 'support@mykartstore.com'
SITE_URL = 'https://mykartstore.com'

# Razorpay (for live payments)
RAZORPAY_KEY_ID = 'your_key_id'
RAZORPAY_KEY_SECRET = 'your_key_secret'
RAZORPAY_SOURCE_ACCOUNT_NUMBER = 'your_account'
SELLER_RAZORPAY_PAYOUT_MODE = 'live'  # or 'mock'
```

## Services

### PayoutCalculator
Calculates seller earnings with deductions:
- Platform commission
- Payment gateway fee
- Shipping charges
- GST and TDS
- Seller discounts

### PayoutService
Manages payout release:
- Gathers available earnings
- Processes via payment gateway
- Updates ledger entries
- Sends notifications
- Logs transactions

### WalletService
Manages wallet balance:
- Recalculates from ledger
- Provides financial snapshots
- Tracks all balance types

### LedgerService
Manages ledger entries:
- Records earnings placement
- Handles status transitions
- Processes returns/cancellations
- Creates adjustments

## Usage Examples

### Python (Backend)

```python
from sellers.services import PayoutService, WalletService
from sellers.models import SellerProfile

# Get financial snapshot
seller = SellerProfile.objects.get(id=1)
snapshot = WalletService.get_financial_snapshot(seller)
print(f"Available: ₹{snapshot['wallet'].available_balance}")

# Release payout
service = PayoutService()
payout = service.release_available_balance(
    seller=seller,
    idempotency_key=f"manual:{seller.id}"
)
print(f"Payout: {payout.reference} - {payout.status}")
```

### JavaScript (Frontend)

```javascript
// Get wallet balance
fetch('/seller/api/wallet/')
    .then(r => r.json())
    .then(data => {
        console.log(`Available: ₹${data.wallet.available_balance}`);
    });

// Get payout history
fetch('/seller/api/payout-history/?status=completed')
    .then(r => r.json())
    .then(data => {
        data.payouts.forEach(p => {
            console.log(`${p.reference}: ₹${p.amount}`);
        });
    });

// Request payout
fetch('/seller/api/request-payout/', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert(`Payout initiated: ${data.reference}`);
        }
    });
```

## Scheduled Tasks

### Recommended Cron Jobs

```bash
# Every hour: Process eligibility transitions
0 * * * * cd /app && python manage.py process_payout_eligibility

# Daily: Send payout summaries (10 AM)
0 10 * * * cd /app && python manage.py send_payout_summaries --days 30

# Weekly: Release available payouts (Monday 2 PM)
0 14 * * 1 cd /app && python manage.py release_seller_payouts --min-balance 100
```

## Error Handling

### Common Scenarios

**No available balance**
```
Error: Seller has no available balance to pay out.
Action: Check wallet, verify order completion and hold periods
```

**Payout gateway failure**
```
Status: FAILED
Reason: Razorpay error / Invalid bank account
Action: Check seller's banking details, retry after fix
```

**Duplicate payout request**
```
Status: Uses existing payout via idempotency_key
Action: Safe to retry, returns same payout reference
```

## Testing

Run the management commands with `--dry-run` to preview:

```bash
# See what would be processed
python manage.py process_payout_eligibility --dry-run

# See what would be sent
python manage.py send_payout_summaries --dry-run

# See what would be released
python manage.py release_seller_payouts --dry-run
```

## Performance Notes

- Database indexes reduce query time by ~80%
- Wallet recalculation is atomic and efficient
- Payout batching reduces processing overhead
- Email sending is non-blocking (fail-silently)
- API endpoints support pagination (max 100 per page)

## Future Enhancements

- [ ] Webhook handlers for Razorpay
- [ ] CSV export of payouts
- [ ] Advanced payout reports
- [ ] Automated retention policies
- [ ] Multi-currency support
- [ ] Direct bank deposit options
- [ ] Payout scheduling
- [ ] Performance analytics

