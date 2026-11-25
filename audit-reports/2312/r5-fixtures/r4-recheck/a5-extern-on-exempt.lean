-- R4-A5 独立复验样本（直调 fm_audit 3 环境层）：extern 挂在豁免项上、伪造 Prop ctorIdx、伪造派生 partial；在 R5 均退 1
module
public section
inductive Color | red | green
attribute [extern "evil_ctor"] Color.ctorIdx
attribute [extern "evil_impl"] Color.ctorIdx._impl
