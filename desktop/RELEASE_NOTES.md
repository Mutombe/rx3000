Labels print.

**If you have a Zebra, it now speaks Zebra**

A label printer speaks its own language, and this application was not speaking
it. It drew the sticker as a PDF and asked Windows to hand that to the
printer's driver, which Windows will only do if something on the machine has
registered itself as able to print a PDF to a named printer. Edge does not.
Acrobat does, which is why this worked on some tills and not others and looked
like a fault with the printer.

A Zebra needs none of that. The sticker now goes to it in ZPL, straight to the
spooler, with the driver bypassed and nothing to install on the till. It is the
same sticker, drawn from the same measurements as the preview on screen, at
your printer's own resolution.

Nobody is asked which language their printer speaks. Windows already says so:
it calls the printer something like "ZDesigner ZD421 203dpi ZPL", which names
the language and the resolution, and that is now read rather than guessed.

**The reprint screen was sending the wrong thing entirely**

Printing from the dispensing history said "1 label(s) printed" and nothing came
off the roll. It was sending receipt printer codes, whatever the till was set
to, and a label printer accepts that job and throws it away. It now prints by
the same route the dispensary uses.

**"The print window was blocked"**

The application would ask you to allow pop ups for this site. There is no site
and no setting to find, because the desktop application is not a browser. Every
document now prints without needing a window: labels, receipts, claim copies,
waybills, statements and quotations.

Two of those printed nothing at all rather than saying anything. A claim copy
or a waybill printed from the desktop application opened no window, showed no
message and produced no paper.

**The barcode prints once, on the label**

The dispensing label has always carried the script barcode along its bottom. A
second sticker carrying only the barcode was also printing on every item,
which is two stickers where one will do. It is a tick again, for the pack that
needs the number somewhere else as well.

**When something will not print, it now says why**

"The printer accepted no document" was Windows talking, and it told nobody
anything. A printer refuses a job for three reasons in practice, and all three
are things you can see from where you are standing: it is switched off, it is
out of paper, or it is paused. It now says which, and names the printer.

The till and the dispensary used to throw the printer's answer away and
quietly open the print dialogue instead, so a till appeared to print sometimes
and ask you other times, for no reason anybody could see. The sale and the
dispensing still stand, and now you are told why the paper did not come out.

**Each document goes where you sent it**

Dispensing labels to the label roll, receipts to the receipt printer, claim
copies to the A4 printer. Anything you have not pointed anywhere follows the
label roll, so one printer still does everything until you say otherwise.
These belong to the till they are set on, because the printer is plugged in
there.
