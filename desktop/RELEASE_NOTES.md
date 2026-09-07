Fixes the till reporting that it cannot reach its server when the
server is running normally.

The application now carries its server address itself, instead of
depending on the shell handing it over before the first screen loads.

- A read waits while a server comes back rather than failing. Anything
  that takes money or moves stock is still attempted once only, so
  nothing can be paid or dispensed twice.
- The application carries its own typeface, so it reads the same on a
  till as in a browser, including with no line.
- The window title is the product name; the server this till talks to
  is on the This Till screen.
- Lists show a new row the moment you save it.
