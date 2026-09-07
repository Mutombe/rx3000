Opening the till first thing no longer shows server errors while the
server is starting up.

- A read waits for the server to come up instead of failing. Anything
  that takes money or moves stock is still attempted once only, so
  nothing is ever paid or dispensed twice.
- The application carries its own typeface, so it reads the same on a
  till as in a browser, including with no line.
- The window title is the product name; the server this till talks to
  is on the This Till screen.
- Lists show a new row the moment you save it.
- Signing in and every page load are several times faster.
