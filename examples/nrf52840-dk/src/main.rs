#![no_main]
#![no_std]

// UART initialization is based on embedded-debugger's qualified DK smoke example.
// No UICR section, NVMC operation, external actuator, radio or UART receive path.
use core::arch::{asm, global_asm};
use core::panic::PanicInfo;
use core::ptr::{read_volatile, write_volatile};

global_asm!(
    r#"
    .syntax unified
    .cpu cortex-m4
    .thumb
    .section .vector_table,"a",%progbits
    .align 2
    .global VECTOR_TABLE
VECTOR_TABLE:
    .word 0x20040000
    .word Reset
    .rept 62
    .word DefaultHandler
    .endr
    .section .text.Reset,"ax",%progbits
    .align 2
    .global Reset
    .type Reset,%function
    .thumb_func
Reset:
    cpsid i
    bl rust_main
    b .
    .section .text.DefaultHandler,"ax",%progbits
    .align 2
    .global DefaultHandler
    .type DefaultHandler,%function
    .thumb_func
DefaultHandler:
    b .
"#
);

const UART: usize = 0x4000_2000;
const READY: &[u8] = b"HIL_NRF52840_DK_READY v1\r\n";
const BUILD: &[u8] = concat!(
    "HIL_NRF52840_DK_BUILD v1 ",
    env!("HIL_DK_VARIANT"),
    " ",
    env!("HIL_DK_BUILD_ID"),
    "\r\n"
)
.as_bytes();
const HEARTBEAT: &[u8] = b"HIL_NRF52840_DK_HEARTBEAT\r\n";

unsafe fn write(address: usize, value: u32) {
    unsafe { write_volatile(address as *mut u32, value) };
}

unsafe fn send(bytes: &[u8]) {
    for &byte in bytes {
        unsafe {
            write(UART + 0x11c, 0);
            write(UART + 0x51c, u32::from(byte));
            while read_volatile((UART + 0x11c) as *const u32) == 0 {
                asm!("nop", options(nomem, nostack, preserves_flags));
            }
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    unsafe {
        // Volatile development debug disable; never provision/erase UICR here.
        write(0x4000_0558, 0x5a);
        write(UART + 0x500, 0);
        write(UART + 0x508, 0xffff_ffff);
        write(UART + 0x510, 0xffff_ffff);
        write(UART + 0x514, 0xffff_ffff);
        write(UART + 0x50c, 6); // DK application UART TX: P0.06.
        write(UART + 0x524, 0x01d7_e000); // 115200, 8N1, no flow control.
        write(UART + 0x56c, 0);
        write(UART + 0x500, 4);
        write(UART + 0x008, 1);
        send(READY);
        send(BUILD);
    }
    loop {
        for _ in 0..4_000_000 {
            unsafe { asm!("nop", options(nomem, nostack, preserves_flags)) };
        }
        unsafe { send(HEARTBEAT) };
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    loop {
        unsafe { asm!("nop", options(nomem, nostack, preserves_flags)) };
    }
}
