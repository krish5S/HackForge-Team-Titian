# Meridian Global expense policy ? September 2026

Fictional demo policy. All limits are USD equivalents using the supplied transaction FX rate.
These values are implementation assumptions authorized by the user, not original PRD constants.
Round final monetary allocations to cents using ROUND_HALF_UP. Never use binary floats.

## 1.1 Monthly category limits
Entertainment reimbursements are capped at USD 300 per employee per calendar month.
Eligible claims awaiting review reserve budget; rejected claims do not. Allocate budget in
transaction date/time order, breaking ties by receipt ID. Recalculate when older expenses arrive.

## 2.1 Business-trip meal limits
Meals outside the employee's home city are business-trip meals. Eligible trip meals are capped
per employee, transaction city and calendar day: Jakarta USD 40, Kuala Lumpur USD 45,
Chicago USD 75, New York USD 90, and all other cities USD 60. Unused daily limits do not roll over.

## 3.1 Local meals
Meals in the employee's home city require review unless they are documented client meals.
A missing home city or transaction city requires review; do not assume travel status.

## 4.1 Excluded items
Alcohol is not reimbursable. Remove its line-item amount and proportional shares of tax,
tip and other charges. Divide the excluded item subtotal by the complete printed subtotal.
Missing or inconsistent item amounts require review rather than guessing an exclusion.

## 5.1 Client and guest documentation
Client meals require a client name and attendee count. Meals with more than one attendee
require attendee names matching the count. Missing documentation requires review.

## 6.1 Approval and suspicious splitting
A claim strictly above USD 500 requires recorded approval; exactly USD 500 does not.
Claims from the same employee, merchant and day, each below USD 500 but together above
USD 500, require review for split transactions. Three or more claims by the same employee
in one category in a month at 90?100 percent of USD 500 require review for threshold hugging.

## 7.1 Itemized receipts
Claims strictly above USD 25 require a fully itemized receipt. Missing itemization requires review.

## 8.1 Tips
Reimbursable tip is capped at 20 percent of the eligible pretax subtotal. Apply item exclusions
before the tip cap so excluded tips are never subtracted twice.

## 9.1 Submission deadline
Submit within 30 calendar days of the transaction date. Later submissions require review.
A submission earlier than its transaction date requires review for inconsistent dates.

## 10.1 Evidence and duplicates
Unreadable images, non-receipts, missing essential extraction or FX data, failed arithmetic
checks, and a forensic score of 60 or more require review. A score is evidence, not proof of fraud.
Confirmed duplicate submissions are rejected, preserving the earliest submitted original.
Possible duplicates and cross-employee duplicate claims require review. Break arrival ties by ID.

## 11.1 Reasonable expenses
Unusually lavish expenses should generally be reasonable for the business occasion.
This deliberately vague clause must be flagged as ambiguous and must not become an automatic rule.

## 12.1 Decision explanations
Every policy adjustment and review reason must cite its numbered clause. Approved claims receive
the eligible amount after caps; rejected claims receive zero; review claims have a proposed amount
but no confirmed reimbursement. Daily and monthly caps reduce payment rather than imply rejection.
