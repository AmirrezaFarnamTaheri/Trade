//! Pure permission floor, not caller-authenticated capability.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthorityTier { T0, T1, T2 }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    PauseEntries, ExitOnly, Halt,
    ApproveProposal, Flatten,
    ProvisionCredential, ResolveUnknownOrder, HardStop,
}
pub fn permits(tier: AuthorityTier, action: Action) -> bool {
    use Action::*;
    match action {
        PauseEntries | ExitOnly | Halt => true,
        ApproveProposal | Flatten => matches!(tier, AuthorityTier::T1 | AuthorityTier::T2),
        ProvisionCredential | ResolveUnknownOrder | HardStop => tier == AuthorityTier::T2,
    }
}
