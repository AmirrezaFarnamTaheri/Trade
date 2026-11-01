//! B2 chaos-suite report: runs every seeded Fake Venue fixture and writes JSON.
//! Usage: gym-chaos OUT.json [SEEDS]. Exit 1 if any invariant is violated.
use exec_core::fake_venue::{run, Outcome, FIXTURES};

fn q(s: &str) -> String {
    let mut o = String::from('"');
    for ch in s.chars() {
        match ch {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

fn outcome(o: &Outcome) -> String {
    let list = |v: &[String]| v.iter().map(|s| q(s)).collect::<Vec<_>>().join(",");
    format!(
        "{{\"seed\":{},\"funded_post_count\":{},\"venue_orders\":{},\"venue_filled\":{},\"recognized_filled\":{},\"lifecycle\":{},\"effect\":{},\"settlement\":{},\"reservation_released\":{},\"frozen\":{},\"incident\":{},\"trace\":[{}],\"violations\":[{}]}}",
        o.seed, o.funded_post_count, o.venue_orders, o.venue_filled, o.recognized_filled,
        q(&format!("{:?}", o.lifecycle)), q(&format!("{:?}", o.effect)), q(&format!("{:?}", o.settlement)),
        o.reservation_released, o.frozen, o.incident.map(q).unwrap_or("null".into()),
        list(&o.trace), list(&o.violations))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let Some(out) = args.get(1) else {
        eprintln!("usage: gym-chaos OUT.json [SEEDS]");
        std::process::exit(2);
    };
    let seeds: u64 = match args.get(2).map(|s| s.parse()) {
        None => 500,
        Some(Ok(n)) if (1..=100_000).contains(&n) => n,
        _ => { eprintln!("SEEDS must be 1..=100000"); std::process::exit(2); }
    };
    let mut rows = Vec::new();
    let mut total_violations = 0usize;
    for f in FIXTURES {
        let (mut settled, mut frozen, mut violations) = (0u64, 0u64, 0usize);
        let mut incidents: Vec<&str> = Vec::new();
        let mut first_violation: Option<Outcome> = None;
        for seed in 1..=seeds {
            let o = run(f, seed);
            if o.reservation_released { settled += 1 }
            if o.frozen { frozen += 1 }
            if let Some(i) = o.incident { if !incidents.contains(&i) { incidents.push(i) } }
            if !o.violations.is_empty() {
                violations += o.violations.len();
                first_violation.get_or_insert(o);
            }
        }
        total_violations += violations;
        let example = first_violation.unwrap_or_else(|| run(f, 717));
        rows.push(format!(
            "{{\"fixture\":{},\"runs\":{},\"settled\":{},\"frozen\":{},\"violations\":{},\"incidents\":[{}],\"example\":{}}}",
            q(f), seeds, settled, frozen, violations,
            incidents.iter().map(|s| q(s)).collect::<Vec<_>>().join(","), outcome(&example)));
    }
    let json = format!(
        "{{\"report\":\"b2-chaos-suite\",\"engine\":\"exec-core fake_venue/1\",\"seeds_per_fixture\":{},\"invariants\":[\"no POST before durable intent\",\"at most one venue order per intent\",\"no resend after first byte\",\"recognized fills never exceed venue fills\",\"settle only on exact venue truth\",\"per-currency conservation\",\"unresolved keeps slot+reservation frozen with incident\"],\"passed\":{},\"total_violations\":{},\"funded_authority\":false,\"fixtures\":[{}]}}\n",
        seeds, total_violations == 0, total_violations, rows.join(","));
    if let Err(e) = std::fs::write(out, json) {
        eprintln!("cannot write report: {e}");
        std::process::exit(2);
    }
    println!("{} fixtures x {seeds} seeds, {total_violations} violations -> {out}", FIXTURES.len());
    if total_violations != 0 { std::process::exit(1) }
}
