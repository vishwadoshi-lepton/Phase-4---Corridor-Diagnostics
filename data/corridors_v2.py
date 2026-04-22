"""
corridors_v2.py

Test corridor definitions for the 6-stage diagnostic algorithm.
Each corridor is a *topologically verified* chain of road segments
(endpoint-to-startpoint gap <= 35m). Segment order is physical: index 0 is
the most upstream, index N-1 is the most downstream.

Three NEW blind-test corridors + the four original corridors for regression.
"""

# --- NEW BLIND-TEST CORRIDORS ---

JBN = {
    "id": "JBN",
    "name": "Jedhe Chowk -> Bhairoba -> Kavdipath -> Naygaon Phata",
    "chain": [
        ("df403320-30c6-4580-909b-133cb250272c", "Swargate Jedhe Chowk To Vega Center"),
        ("baa7b1ec-ce05-439d-8ca8-3690154be8ab", "Vega Center To ST Depo"),
        ("bef72dd6-13e7-4f90-93b0-87dd69757b54", "ST Depo To Kumar Pacific Mall"),
        ("e64023ba-7bde-4193-b155-e2383c02a11c", "Kumar Pacific Mall To Dhobi Ghat"),
        ("cf70d7fd-be37-4858-bdbf-607de4d54f44", "Dhobi Ghat To Khanya Maruti Chowk"),
        ("a8922f52-5074-4984-9252-0598e572eb7d", "Khanya Maruti Chowk To St. Mery Chowk"),
        ("0e8fe827-cf32-4d6f-965d-e37a7bcca61b", "St. Mery Chowk To Turf Club"),
        ("ff90138f-655c-4095-b39a-6745fe1ca5c6", "Turf Club To Bhairoba Nala"),
        ("bc57e4fc-ed4d-403b-83e8-318f27d66d83", "Bhairoba Nala To Kalubai Junction"),
        ("b94cb70f-345b-4fa6-814c-703417222d31", "Kalubai Junction To Ramtekdi"),
        ("8d81b1c6-dc1e-491d-a0b1-9437f8ee96fb", "Ramtekdi To Megacenter"),
        ("c002f66c-cabd-409f-a4f6-29fc59e80c83", "Megacenter To Gadital"),
        ("b9fad205-b528-46c5-8376-929e97f36a54", "Gadital To 15 Number"),
        ("8c4f5c97-a4b9-4112-b460-8f7d1764eceb", "15 Number To Shewalwadi"),
        ("38bda60b-2416-40be-8162-262263f9be6a", "Shewalwadi To Kavdipath Toll Naka"),
        ("551e7a15-979d-4ea5-8769-55abab9022fe", "Kavdipath Toll Naka To Fursungi Road Junction"),
        ("65618798-8c14-4be6-b832-6edb4b275905", "Fursungi Road Junction To Kadamwak Wasti"),
        ("832422ab-2802-41db-9ee7-7b7ffb237e93", "Kadamwak Wasti To Rajlaxmi Mangalkaryalay"),
        ("048a330a-c35f-417d-86f8-6b8966c982c6", "Rajlaxmi Mangalkaryalay To Kunjir Lawns"),
        ("d985d544-5d78-40e3-89d6-0866dc443cfa", "Kunjir Lawns To Naygaon Phata"),
    ],
}

BAP = {
    "id": "BAP",
    "name": "Bapodi Junction -> Khadki -> Holkar Bridge -> Parnkuti -> Wadgaonsheri",
    "chain": [
        ("871e41d4-4583-45a6-a266-f3745a4cdb36", "Bapodi Junction To Kirloskar Company"),
        ("cbdb3e29-5142-4dd0-a1a6-aa29356b8fad", "Kirloskar company To Khadki Bajar Bus Stop"),
        ("9ab128df-bc72-432c-a886-73e85cbb7a64", "Khadki bajar bus stop To Methdist Church"),
        ("0c3b09de-2cdf-4a32-8319-e1007e75211a", "Methdist Church To Holkar Bridge"),
        ("24ef95ba-301c-40be-b839-3391ef5ec921", "Holkar Bridge To Chandrma Chowk"),
        ("d1d48fa6-819a-4a4b-a69a-d442fdac393e", "Chandrma Chowk To Sadalbaba Chowk"),
        ("cf54d9e0-29dd-4089-835f-e9bf1e0c5599", "Sadalbaba Chowk To Parnkuti"),
        ("b295939a-160c-42e0-bc69-ac5ed9b308e6", "Parnkuti To Gunjan Chowk"),
        ("79d6ed13-3e4d-47c2-87a9-9a506b4c987f", "Gunjan Chowk To Shastrinagar"),
        ("a5379fc6-9dc3-446f-bab6-f28d7f9aee11", "Shastrinagar To Ramwadi Junction"),
        ("2223e531-30a2-4ce4-9c0a-80f3fa4ba83d", "Ramwadi Junction To Wadgaonsheri"),
    ],
}

HDV = {
    "id": "HDV",
    "name": "Hadapsar Gadital -> Fursungi -> Urali Devachi -> Dive Ghat",
    "chain": [
        ("c962ba4c-bef1-4ea0-93e5-a34d1c4ec5f0", "Hadapsar Gadital To Ayppa Mandir"),
        ("394b44de-e054-4de5-bcb3-99a7346376a4", "Ayppa Mandir To Kaleborate Nagar Road"),
        ("c7715bef-2a20-4176-baea-ec424dee69fe", "Kaleborate Nagar Road To Fursungi gaon Road Junction"),
        ("7f50dea1-79d5-43e6-8ea8-b816cecefde8", "Fursungi gaon Road Junction To Katraj Road Junction"),
        ("13dd3173-f6df-480f-ab16-e4db1b733679", "Katraj Road Junction To Urali Devachi Road Junction"),
        ("d8cc9d18-fabd-4dc8-b8e8-ea2441d9d8a1", "Urali Devachi Road Junction To Wadki"),
        ("059a30bb-7bbc-4e6e-8719-5710d9ad94e0", "Wadki To Diveghat start"),
        ("80398eb0-7035-47a8-9681-b1f4e84e1354", "Diveghat start To Diveghat End"),
    ],
}

NEW_CORRIDORS = [JBN, BAP, HDV]

# --- ORIGINAL FOUR CORRIDORS (for regression against previous results) ---
# road_ids in chain order as used in the prior session's diagnosis.

JEDHE_KATRAJ = {
    "id": "JEDHE_KATRAJ",
    "name": "Jedhe Chowk -> Katraj Ghat",
    "corridor_id": "cor_01kn4e0e2f7mhkbqbx6x8w0xwm",
}

KOREGAON_KESHAV = {
    "id": "KOREGAON_KESHAV",
    "name": "Koregaon Park Jn -> Keshavnagar (ABC Farm/Tadigutta/Mundhwa)",
    "corridor_id": "cor_01kn4e0e2g9t4995eje0k423xz",
}

PUNE_KANHA = {
    "id": "PUNE_KANHA",
    "name": "Pune Station -> Kanha Hotel",
    "corridor_id": "cor_01kn4e0e2hjxvs594yw6jfa8yg",
}

MUNDHWA_KOLWADI = {
    "id": "MUNDHWA_KOLWADI",
    "name": "Mundhwa -> Keshavnagar -> Manjri -> Kolwadi (E-outbound)",
    "corridor_id": "cor_01kn4e0e2nx6wbq5vp8dnqabjk",
}

ORIGINAL_CORRIDORS = [JEDHE_KATRAJ, KOREGAON_KESHAV, PUNE_KANHA, MUNDHWA_KOLWADI]
