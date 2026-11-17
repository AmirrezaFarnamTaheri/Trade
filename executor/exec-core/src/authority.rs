//! Pure permission floor, not caller-authenticated capability.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthorityTier {
    Observer,
    Operator,
    Administrator,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    PauseEntries,
    ExitOnly,
    Halt,
    ApproveProposal,
    Flatten,
    ProvisionCredential,
    ResolveUnknownOrder,
    HardStop,
}
pub fn permits(tier: AuthorityTier, action: Action) -> bool {
    use Action::*;
    match action {
        PauseEntries | ExitOnly | Halt => true,
        ApproveProposal | Flatten => {
            matches!(tier, AuthorityTier::Operator | AuthorityTier::Administrator)
        }
        ProvisionCredential | ResolveUnknownOrder | HardStop => {
            tier == AuthorityTier::Administrator
        }
    }
}
