"""Exact root-owned shared-slot worker units; no runtime template generation."""

from types import MappingProxyType

SHARED_WORKER_POLKIT_SHA256 = "fcc46015f030e284b1bf4f5510cfd99ddc98044d014270496aef05e06a0bfa46"

SHARED_WORKER_TEMPLATE_SHA256 = MappingProxyType(
    {
        ("01", 900): "d9b69dd5205d85b0bc74944b78b59d8c45d72af74f4c2b09f8f13b953f1291b3",
        ("01", 3600): "66bbde59cae3237845bce1e656f8f99576bbbbd18081667f7edd475346b57196",
        ("01", 7200): "18e373f3a0d59189932a3b00b4e9b8953508eed974aa20b85f693f935534b646",
        ("02", 900): "9af92c62e95b2fd739c39f523f81b3ce460ba0ca5af5538e58d85ab3d6f9019c",
        ("02", 3600): "2af43b087adc26919fe42e046647c1af3f3c09eefa07ebbda1e3e3997bd7deb1",
        ("02", 7200): "032a8d9fe3d0d3c381a5302869427f68d9f5b7a55aa4a6563dca02f365da6c4e",
        ("03", 900): "899eeca8b0798c36e5a3a91652b60654c0ba96fc27f02d46c151ab3ca74d578e",
        ("03", 3600): "7cb41578b62778474347dfee7d062ed570933ec9960d61184c6cd336c50069d1",
        ("04", 900): "26c147a25fdeeb552f9ed93f1c4498aec1492603e0392b99af49dcf4a64e0ffb",
        ("04", 3600): "6c9411543e5094bc277699b2f9bef6a4fc3cea7632d10fdb3ae6df2c4eb04f13",
        ("05", 1800): "f8ef559ec8a14a1dea034c95846f5cea49af02be49eb7060be83178f9e739221",
    }
)
