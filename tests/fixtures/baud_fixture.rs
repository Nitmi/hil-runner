// Host-only native CLI fixture. No serial/Bluetooth/debug API or third-party dependency.
use std::{
    env, fs,
    io::{self, Write},
    path::PathBuf,
    thread,
    time::Duration,
};

fn quote(value: &str) -> String {
    let mut result = String::from("\"");
    for character in value.chars() {
        match character {
            '\\' => result.push_str("\\\\"),
            '"' => result.push_str("\\\""),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            other => result.push(other),
        }
    }
    result.push('"');
    result
}

fn option(args: &[String], key: &str) -> String {
    let index = args
        .iter()
        .position(|value| value == key)
        .expect("required fixture option");
    args[index + 1].clone()
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let root = env::current_exe().unwrap().parent().unwrap().to_owned();
    let mut audit = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(root.join("calls.log"))
        .unwrap();
    writeln!(audit, "{}", args.join(" ")).unwrap();
    if args == ["--version"] {
        println!("baud 0.1.2");
    } else if args.first().map(String::as_str) == Some("list") {
        println!("{{\"ok\":true,\"ports\":[{{\"device\":\"COM999\",\"vid\":65535,\"pid\":1,\"serial_number\":\"CI-A\",\"interface\":null}}]}}");
    } else if args.first().map(String::as_str) == Some("monitor") {
        if fs::read_to_string(root.join("mode.txt"))
            .unwrap_or_default()
            .trim()
            == "hang"
        {
            thread::sleep(Duration::from_secs(60));
        }
        let build = fs::read_to_string(root.join("next-build.txt")).unwrap();
        let text = format!(
            "HIL_READY v1\n{}\nHIL_HEARTBEAT\nHIL_HEARTBEAT\nHIL_HEARTBEAT\n",
            build.trim()
        );
        let directory = PathBuf::from(option(&args, "--log-dir"));
        fs::create_dir_all(&directory).unwrap();
        let events = directory.join("fixture.events.jsonl");
        let log = directory.join("fixture.log");
        // Native runtime validates the text and byte count from this unchanged event file.
        fs::write(
            &events,
            format!(
                "{{\"type\":\"recv\",\"bytes\":{},\"text\":{}}}\n",
                text.len(),
                quote(&text)
            ),
        )
        .unwrap();
        fs::write(&log, &text).unwrap();
        thread::sleep(Duration::from_millis(1200));
        println!("{{\"ok\":true,\"exit_code\":0,\"port\":\"COM999\",\"baudrate\":115200,\"duration_ms\":1200,\"events_file\":{},\"log_file\":{}}}", quote(&events.display().to_string()), quote(&log.display().to_string()));
        io::stdout().flush().unwrap();
    } else {
        std::process::exit(7);
    }
}
