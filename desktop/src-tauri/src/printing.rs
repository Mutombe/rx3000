//! Printing straight to a printer, with no dialog.
//!
//! A dispensary prints a label for every item on every script. A print dialog
//! in that loop is a keystroke and a decision each time, and the person doing
//! it has a queue at the counter — so the labels have to come off the roll the
//! moment the sale completes, the way they do on every other till in the trade.
//!
//! A browser cannot do this: `window.print()` always asks. So the shell does
//! it, sending bytes straight to the Windows spooler in RAW mode, which is how
//! ESC/POS and ZPL are meant to be delivered. The printer's own driver is
//! bypassed entirely — the bytes are the document.
//!
//! This lives in the desktop app rather than in a separate service on purpose:
//! a pharmacy downloads one thing.

#[cfg(windows)]
mod windows_impl {
    use std::ffi::c_void;
    use std::iter::once;
    use std::os::windows::ffi::OsStrExt;

    // Declared here rather than pulling in a Windows bindings crate. Four
    // functions and two structs, against several hundred megabytes of generated
    // bindings and the build time that comes with them — on a project whose
    // installer is two megabytes.
    #[link(name = "winspool")]
    extern "system" {
        fn OpenPrinterW(name: *mut u16, handle: *mut *mut c_void, defaults: *mut c_void) -> i32;
        fn ClosePrinter(handle: *mut c_void) -> i32;
        fn StartDocPrinterW(handle: *mut c_void, level: u32, info: *mut DocInfo1) -> u32;
        fn EndDocPrinter(handle: *mut c_void) -> i32;
        fn StartPagePrinter(handle: *mut c_void) -> i32;
        fn EndPagePrinter(handle: *mut c_void) -> i32;
        fn WritePrinter(handle: *mut c_void, buf: *const c_void, len: u32, written: *mut u32) -> i32;
        fn EnumPrintersW(flags: u32, name: *mut u16, level: u32, buf: *mut u8,
                         buf_size: u32, needed: *mut u32, returned: *mut u32) -> i32;
    }

    #[repr(C)]
    struct DocInfo1 {
        doc_name: *mut u16,
        output_file: *mut u16,
        datatype: *mut u16,
    }

    #[repr(C)]
    struct PrinterInfo4 {
        printer_name: *mut u16,
        server_name: *mut u16,
        attributes: u32,
    }

    const PRINTER_ENUM_LOCAL: u32 = 0x0000_0002;
    const PRINTER_ENUM_CONNECTIONS: u32 = 0x0000_0004;

    fn wide(value: &str) -> Vec<u16> {
        std::ffi::OsStr::new(value).encode_wide().chain(once(0)).collect()
    }

    /// Every printer this machine can see, local and networked.
    pub fn list() -> Result<Vec<String>, String> {
        unsafe {
            let flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS;
            let mut needed = 0u32;
            let mut returned = 0u32;
            // First call sizes the buffer; it is expected to fail.
            EnumPrintersW(flags, std::ptr::null_mut(), 4, std::ptr::null_mut(), 0,
                          &mut needed, &mut returned);
            if needed == 0 {
                return Ok(Vec::new());
            }
            let mut buffer = vec![0u8; needed as usize];
            let ok = EnumPrintersW(flags, std::ptr::null_mut(), 4, buffer.as_mut_ptr(),
                                   needed, &mut needed, &mut returned);
            if ok == 0 {
                return Err("Windows would not list the printers on this machine.".into());
            }
            let infos = buffer.as_ptr() as *const PrinterInfo4;
            let mut out = Vec::with_capacity(returned as usize);
            for i in 0..returned as usize {
                let entry = &*infos.add(i);
                if entry.printer_name.is_null() {
                    continue;
                }
                let mut len = 0usize;
                while *entry.printer_name.add(len) != 0 {
                    len += 1;
                }
                let name = std::slice::from_raw_parts(entry.printer_name, len);
                out.push(String::from_utf16_lossy(name));
            }
            out.sort();
            Ok(out)
        }
    }

    /// Send bytes to a named printer as a RAW job — no driver, no dialog.
    pub fn print_raw(printer: &str, data: &[u8]) -> Result<usize, String> {
        if printer.trim().is_empty() {
            return Err("No printer was named.".into());
        }
        if data.is_empty() {
            return Err("There was nothing to print.".into());
        }
        unsafe {
            let mut name = wide(printer);
            let mut handle: *mut c_void = std::ptr::null_mut();
            if OpenPrinterW(name.as_mut_ptr(), &mut handle, std::ptr::null_mut()) == 0 {
                return Err(format!("Windows could not open the printer \"{printer}\". \
                                    Check the name matches one it lists."));
            }
            // Every early return past this point has to close the handle, so the
            // work is done in a closure and the handle is closed once after it.
            let result = (|| -> Result<usize, String> {
                let mut doc_name = wide("RX5000 label");
                let mut datatype = wide("RAW");
                let mut info = DocInfo1 {
                    doc_name: doc_name.as_mut_ptr(),
                    output_file: std::ptr::null_mut(),
                    datatype: datatype.as_mut_ptr(),
                };
                if StartDocPrinterW(handle, 1, &mut info) == 0 {
                    return Err("The printer accepted no document.".into());
                }
                if StartPagePrinter(handle) == 0 {
                    EndDocPrinter(handle);
                    return Err("The printer accepted no page.".into());
                }
                let mut written = 0u32;
                let ok = WritePrinter(handle, data.as_ptr() as *const c_void,
                                      data.len() as u32, &mut written);
                EndPagePrinter(handle);
                EndDocPrinter(handle);
                if ok == 0 {
                    return Err("The printer refused the data.".into());
                }
                Ok(written as usize)
            })();
            ClosePrinter(handle);
            result
        }
    }
}

#[cfg(not(windows))]
mod windows_impl {
    pub fn list() -> Result<Vec<String>, String> {
        // Linux and macOS reach a thermal printer through CUPS or a device
        // node, which is a different job from this one. Reported honestly so
        // the application offers the print dialog instead of a broken button.
        Ok(Vec::new())
    }

    pub fn print_raw(_printer: &str, _data: &[u8]) -> Result<usize, String> {
        Err("Direct printing is only wired up for Windows on this build.".into())
    }
}

/// Printers this machine can see. Empty means "use the print dialog".
#[tauri::command]
pub fn list_printers() -> Result<Vec<String>, String> {
    windows_impl::list()
}

/// Print bytes on a named printer with no dialog.
///
/// Takes the payload as numbers because that is what survives the bridge
/// between the web page and the shell without an encoding argument to get
/// wrong; ESC/POS is not text and must not be treated as any.
#[tauri::command]
pub fn print_raw(printer: String, data: Vec<u8>) -> Result<usize, String> {
    windows_impl::print_raw(&printer, &data)
}
