#[path = "../research_worker.rs"]
mod research_worker;

fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.is_empty() || args.len() > 2 || (args.len() == 2 && args[1] != "--boundary-probe") {
        eprintln!("usage: gym-research-worker <protected-install-directory> [--boundary-probe]");
        std::process::exit(2);
    }
    match research_worker::launch(std::path::Path::new(&args[0]), args.len() == 2) {
        Ok(code) => std::process::exit(i32::try_from(code).unwrap_or(125)),
        Err(error) => {
            eprintln!("R0 refused: {error}");
            std::process::exit(125);
        }
    }
}
