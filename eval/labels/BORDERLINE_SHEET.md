# Judge calibration: borderline answers (labelling sheet)

Label each answer **pass** or **fail** on your own, before seeing anyone else's labels or the judge's.
Use the same rubric as the judge: an answer passes when it is correct and grounded in the evidence, answers the
question, and does not state anything the evidence contradicts or does not support. Extra correct detail is fine;
a dropped caveat, an unsupported addition or a wrong value is a fail. If unsure, pick the closer one and say why.

Write your labels to `eval/labels/borderline_<your-name>.csv` with the header `id,label,comment`.

## b01a

**Question:** What is the debit rate on the Get Clássica?

**Reference:** Debit (débito) is 1.69% on the Get Clássica (published 'from' rate).

**Evidence:**

> [https://site.getnet.com.br/maquininha/get-classica/] Published "from" rates (a partir de) with a single rate (taxa única) for Mastercard, Visa, Elo and Amex: debit (débito) 1.69%; credit in one payment (crédito à vista, 1x) 3.79%; installment credit (crédito parcelado) 2x 7.98%, 3x 8.47%, 4x 8.96%, 5x 9.45%, 6x 9.94%, 7x 10.43%, 8x 10.92%, 9x 11.41%, 10x 11.90%, 11x 12.39%, 12x 12.88%. Card installments on the machine go from 1x to 12x. The page does not publish a Pix rate for this model.

**Answer:** The Get Clássica debit rate is about 1.7%.

## b01b

**Question:** What is the debit rate on the Get Clássica?

**Reference:** Debit (débito) is 1.69% on the Get Clássica (published 'from' rate).

**Evidence:**

> [https://site.getnet.com.br/maquininha/get-classica/] Published "from" rates (a partir de) with a single rate (taxa única) for Mastercard, Visa, Elo and Amex: debit (débito) 1.69%; credit in one payment (crédito à vista, 1x) 3.79%; installment credit (crédito parcelado) 2x 7.98%, 3x 8.47%, 4x 8.96%, 5x 9.45%, 6x 9.94%, 7x 10.43%, 8x 10.92%, 9x 11.41%, 10x 11.90%, 11x 12.39%, 12x 12.88%. Card installments on the machine go from 1x to 12x. The page does not publish a Pix rate for this model.

**Answer:** Debit on the Get Clássica is 1.69%, a published 'from' rate (a partir de). Credit in one payment is 3.79%.

## b02a

**Question:** How long until I receive a crediário sale?

**Reference:** Up to 2 business days after capture, in a single payment, net of the discount rate.

**Evidence:**

> [https://site.getnet.com.br/crediario/] The merchant receives Crediário sales in up to 2 business days (2 dias úteis) after the transaction is captured, in a single payment (de uma única vez) regardless of the number of installments, net of the discount rate. Crediário sales do not count toward the card machine rental waiver.

**Answer:** You receive it within 2 business days after the sale, all at once.

## b02b

**Question:** How long until I receive a crediário sale?

**Reference:** Up to 2 business days after capture, in a single payment, net of the discount rate.

**Evidence:**

> [https://site.getnet.com.br/crediario/] The merchant receives Crediário sales in up to 2 business days (2 dias úteis) after the transaction is captured, in a single payment (de uma única vez) regardless of the number of installments, net of the discount rate. Crediário sales do not count toward the card machine rental waiver.

**Answer:** You receive it in up to 2 business days, in installments matching the customer's plan.

## b03a

**Question:** Can I sell on Instagram without a card machine?

**Reference:** Yes, with the Payment Link, which is made for selling through WhatsApp or social networks without a machine.

**Evidence:**

> [https://site.getnet.com.br/link-de-pagamento/] Yes: the Payment Link is made for selling through WhatsApp or social networks ("Faça vendas usando o WhatsApp ou sua rede social"), without a card machine (sem maquininha). The merchant creates a link and shares or copies it to the customer. It includes Getnet's anti-fraud (antifraude) and supports sales to foreigners with an RNE identification document. The page does not say whether the merchant needs a website.

**Answer:** Yes. Create a Payment Link and share it with the customer; no card machine is needed.

## b03b

**Question:** Can I sell on Instagram without a card machine?

**Reference:** Yes, with the Payment Link, which is made for selling through WhatsApp or social networks without a machine.

**Evidence:**

> [https://site.getnet.com.br/link-de-pagamento/] Yes: the Payment Link is made for selling through WhatsApp or social networks ("Faça vendas usando o WhatsApp ou sua rede social"), without a card machine (sem maquininha). The merchant creates a link and shares or copies it to the customer. It includes Getnet's anti-fraud (antifraude) and supports sales to foreigners with an RNE identification document. The page does not say whether the merchant needs a website.

**Answer:** Probably yes, the Payment Link seems to work for social media sales.

## b04a

**Question:** What should I do if my machine won't connect, after restarting it?

**Reference:** Connect it to the store Wi-Fi if available, reseat the SIM chip with the machine off, run the communication test; if still offline, ask for a human specialist.

**Evidence:**

> [internal://support-runbook] Synthetic runbook for the mock back office, not official Getnet content. OFFLINE_GPRS_TIMEOUT means the terminal's mobile data session stalled. First-line steps for the merchant, in order: 1) restart the terminal and wait for the network indicator; 2) if Wi-Fi is available, connect the terminal to the store Wi-Fi; 3) with the terminal off, reseat the SIM chip and power it back on; 4) run the communication test described in the Getnet FAQ. If the terminal is still offline on both mobile data and Wi-Fi after these steps, open a ticket with a human specialist for a chip or terminal swap.

**Answer:** Try the store Wi-Fi, then reseat the SIM with the machine off, then run the communication test. If it stays offline, I can hand it to a specialist.

## b04b

**Question:** What should I do if my machine won't connect, after restarting it?

**Reference:** Connect it to the store Wi-Fi if available, reseat the SIM chip with the machine off, run the communication test; if still offline, ask for a human specialist.

**Evidence:**

> [internal://support-runbook] Synthetic runbook for the mock back office, not official Getnet content. OFFLINE_GPRS_TIMEOUT means the terminal's mobile data session stalled. First-line steps for the merchant, in order: 1) restart the terminal and wait for the network indicator; 2) if Wi-Fi is available, connect the terminal to the store Wi-Fi; 3) with the terminal off, reseat the SIM chip and power it back on; 4) run the communication test described in the Getnet FAQ. If the terminal is still offline on both mobile data and Wi-Fi after these steps, open a ticket with a human specialist for a chip or terminal swap.

**Answer:** Reseat the SIM chip with the machine off and run the communication test. If it is still offline, I can hand it to a specialist.

## b05a

**Question:** Is there a fee to receive Pix with Getnet?

**Reference:** The Pix page does not publish Pix fees.

**Evidence:**

> [https://site.getnet.com.br/pix/] The Pix page does not say whether a bank account or a Getnet digital account is required to receive Pix sales, does not describe an activation process, and does not publish Pix fees. Its only advice is to keep registration data with Getnet up to date. See the Get Conta digital account page for where sales can be received. Per the FAQ, Pix allows up to 5 keys (chaves) per account for individuals and 20 for companies.

**Answer:** The Getnet Pix page does not publish a Pix fee, so I can't confirm one.

## b05b

**Question:** Is there a fee to receive Pix with Getnet?

**Reference:** The Pix page does not publish Pix fees.

**Evidence:**

> [https://site.getnet.com.br/pix/] The Pix page does not say whether a bank account or a Getnet digital account is required to receive Pix sales, does not describe an activation process, and does not publish Pix fees. Its only advice is to keep registration data with Getnet up to date. See the Get Conta digital account page for where sales can be received. Per the FAQ, Pix allows up to 5 keys (chaves) per account for individuals and 20 for companies.

**Answer:** Pix is free to receive with Getnet; no fee is published.

## b06a

**Question:** From what monthly sales is the Get Clássica rental waived?

**Reference:** The product page says R$ 10 thousand; the line-up page says R$ 20 thousand; confirm in the simulator or with Getnet.

**Evidence:**

> [https://site.getnet.com.br/maquininha/get-classica/] Monthly rental if the minimum sales volume is not reached: Get Clássica R$ 79.90 per month (for comparison: Get Mini R$ 14.90, Get Smart R$ 129.90, selling by phone R$ 0.00). Rental is waived for the Get Clássica with sales of R$ 10 thousand per month. Curation note: the All Getnet card machines page (https://site.getnet.com.br/todas-as-maquininhas/) states R$ 20 thousand per month for the same waiver, so the two Getnet pages disagree and the applicable threshold should be confirmed in the simulator or with Getnet. Voucher (VA/VR) and Crediário sales do not count toward the rental waiver. No purchase price is published.
> 
> [https://site.getnet.com.br/todas-as-maquininhas/] Rental without minimum sales: Get Clássica R$ 79.90 per month, Get Smart R$ 129.90 per month, selling by phone free. This page states rental-waiver thresholds of R$ 20 thousand per month for the Get Clássica and R$ 40 thousand or R$ 80 thousand per month for the Get Smart; these differ from the thresholds on the individual product pages (R$ 10 thousand and R$ 60 thousand), so the applicable threshold should be confirmed in the simulator or with Getnet.

**Answer:** From R$ 10 thousand in monthly sales, according to the Get Clássica page.

## b06b

**Question:** From what monthly sales is the Get Clássica rental waived?

**Reference:** The product page says R$ 10 thousand; the line-up page says R$ 20 thousand; confirm in the simulator or with Getnet.

**Evidence:**

> [https://site.getnet.com.br/maquininha/get-classica/] Monthly rental if the minimum sales volume is not reached: Get Clássica R$ 79.90 per month (for comparison: Get Mini R$ 14.90, Get Smart R$ 129.90, selling by phone R$ 0.00). Rental is waived for the Get Clássica with sales of R$ 10 thousand per month. Curation note: the All Getnet card machines page (https://site.getnet.com.br/todas-as-maquininhas/) states R$ 20 thousand per month for the same waiver, so the two Getnet pages disagree and the applicable threshold should be confirmed in the simulator or with Getnet. Voucher (VA/VR) and Crediário sales do not count toward the rental waiver. No purchase price is published.
> 
> [https://site.getnet.com.br/todas-as-maquininhas/] Rental without minimum sales: Get Clássica R$ 79.90 per month, Get Smart R$ 129.90 per month, selling by phone free. This page states rental-waiver thresholds of R$ 20 thousand per month for the Get Clássica and R$ 40 thousand or R$ 80 thousand per month for the Get Smart; these differ from the thresholds on the individual product pages (R$ 10 thousand and R$ 60 thousand), so the applicable threshold should be confirmed in the simulator or with Getnet.

**Answer:** The Get Clássica page says R$ 10 thousand, but another Getnet page says R$ 20 thousand; confirm it with Getnet.

## b07a

**Question:** How many installments with crediário?

**Reference:** Up to 48; the maximum term and interest depend on the card issuer.

**Evidence:**

> [https://site.getnet.com.br/crediario/] With Crediário a sale can be split into up to 48 installments (parcelamento em até 48x). The maximum term and the interest rate of the installment plan vary according to the card issuer (emissor do cartão). The simulation on the card machine shows the interest, and the issuer approves the transaction.

**Answer:** Up to 48 installments.

## b07b

**Question:** How many installments with crediário?

**Reference:** Up to 48; the maximum term and interest depend on the card issuer.

**Evidence:**

> [https://site.getnet.com.br/crediario/] With Crediário a sale can be split into up to 48 installments (parcelamento em até 48x). The maximum term and the interest rate of the installment plan vary according to the card issuer (emissor do cartão). The simulation on the card machine shows the interest, and the issuer approves the transaction.

**Answer:** Up to 48 installments, depending on the issuer, with no interest for the buyer.

## b08a

**Question:** What's the Getnet phone number outside the capitals?

**Reference:** 0800-648-8000.

**Evidence:**

> [https://site.getnet.com.br/duvidas/] Phone for capitals and metropolitan regions: 4002-4000 or 4003-4000. Other locations: 0800-648-8000. Customer service hours: 06h to 22h. WhatsApp for customers: 11 97694-6815. Ombudsman (Ouvidoria): 0800 646 3404, Monday to Friday 9h15 to 17h30 except holidays. Self-service: Portal Minha Conta and the Getnet Brasil app.

**Answer:** 0800-648-8000. In capitals and metropolitan regions it is 4002-4000 or 4003-4000; service hours are 6h to 22h.

## b08b

**Question:** What's the Getnet phone number outside the capitals?

**Reference:** 0800-648-8000.

**Evidence:**

> [https://site.getnet.com.br/duvidas/] Phone for capitals and metropolitan regions: 4002-4000 or 4003-4000. Other locations: 0800-648-8000. Customer service hours: 06h to 22h. WhatsApp for customers: 11 97694-6815. Ombudsman (Ouvidoria): 0800 646 3404, Monday to Friday 9h15 to 17h30 except holidays. Self-service: Portal Minha Conta and the Getnet Brasil app.

**Answer:** Call 0800 648 8000 (outside capitals).

## b09a

**Question:** Do I need a CNPJ to open Get Conta?

**Reference:** No: a CPF (individual) or a CNPJ (company) can be used.

**Evidence:**

> [https://site.getnet.com.br/conta-digital/] Registration uses a CPF (individual) or CNPJ (company), and it is not necessary to already have a Getnet product. The account is opened by choosing a machine or another product (maquininhas, link de pagamento or Get Tap) on the site, by WhatsApp (11 97694-6815) or by phone. The page does not state whether an account at another bank is also required; it only says payments can be received in Get Conta itself.

**Answer:** No, a CPF works too if you are an individual.

## b09b

**Question:** Do I need a CNPJ to open Get Conta?

**Reference:** No: a CPF (individual) or a CNPJ (company) can be used.

**Evidence:**

> [https://site.getnet.com.br/conta-digital/] Registration uses a CPF (individual) or CNPJ (company), and it is not necessary to already have a Getnet product. The account is opened by choosing a machine or another product (maquininhas, link de pagamento or Get Tap) on the site, by WhatsApp (11 97694-6815) or by phone. The page does not state whether an account at another bank is also required; it only says payments can be received in Get Conta itself.

**Answer:** Yes, Get Conta is for companies, so you register it with your CNPJ.

## b10a

**Question:** How fast do I receive a Pix sale?

**Reference:** No single fixed deadline: up to one calendar day depending on the Pix model and approval time; marketed as 'in seconds'.

**Evidence:**

> [https://site.getnet.com.br/pix/] There is no single fixed deadline: the time to receive a Pix sale can vary by up to one calendar day (até um dia corrido), depending on the Pix model the customer is eligible for and the time the sale is approved. The site markets Pix as receiving sales "in seconds".

**Answer:** In seconds.

## b10b

**Question:** How fast do I receive a Pix sale?

**Reference:** No single fixed deadline: up to one calendar day depending on the Pix model and approval time; marketed as 'in seconds'.

**Evidence:**

> [https://site.getnet.com.br/pix/] There is no single fixed deadline: the time to receive a Pix sale can vary by up to one calendar day (até um dia corrido), depending on the Pix model the customer is eligible for and the time the sale is approved. The site markets Pix as receiving sales "in seconds".

**Answer:** It can take up to one calendar day, depending on your Pix model and when the sale is approved, although Getnet advertises 'in seconds'.
