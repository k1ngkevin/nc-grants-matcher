"""Seed profiles for NC state agencies.

Each profile is the starting point for matching:
  mission      - plain-language summary of the agency's statutory mandate and priorities.
                 Replace or extend these with official strategic-plan text through the
                 "Improve your matches" panel (POST /api/agencies/{id}/documents).
  keywords     - program words that signal a fit (used for the keyword-fit score).
  aln_prefixes - Assistance Listing (formerly CFDA) number prefixes for federal programs
                 this agency typically receives. "66." = all EPA programs, "97.039" = one program.
  applicant    - "state" (Grants.gov code 00) or "higher_ed" (code 06).

The summaries are written by the team from public agency descriptions and are a
starting point, not official text.
"""

AGENCIES = [
    {
        "id": "doa", "short": "DOA", "name": "Department of Administration", "applicant": "state",
        "mission": "Provides business services to state government including purchasing and contracts, state construction, facility management and motor fleet. Houses advocacy programs: the Council for Women and Youth Involvement, Domestic Violence Commission, Commission of Indian Affairs, Human Relations Commission and the Office for Historically Underutilized Businesses.",
        "keywords": ["domestic violence", "sexual assault", "family violence", "american indian", "tribal", "youth", "women", "fair housing", "human relations", "underutilized business", "state facilities"],
        "aln_prefixes": ["93.671", "93.497", "16.588", "14.401", "14.408"],
    },
    {
        "id": "dac", "short": "DAC", "name": "Department of Adult Correction", "applicant": "state",
        "mission": "Operates state prisons and community supervision (probation and parole). Priorities include safe facilities, reentry and reducing recidivism, substance use and mental health treatment for people in custody, correctional education and job training, and staff recruitment and retention.",
        "keywords": ["corrections", "prison", "incarcerated", "reentry", "recidivism", "probation", "parole", "community supervision", "substance use treatment", "correctional education", "second chance"],
        "aln_prefixes": ["16.812", "16.593", "16.831", "16.606", "16.735", "84.255"],
    },
    {
        "id": "commerce", "short": "Commerce", "name": "Department of Commerce", "applicant": "state",
        "mission": "Leads economic development, business recruitment and expansion, rural economic development, and the state workforce system (NCWorks, Workforce Solutions). Administers unemployment insurance through the Division of Employment Security, plus community development block grants for small towns, trade and tourism.",
        "keywords": ["economic development", "workforce", "job training", "apprenticeship", "unemployment insurance", "rural development", "manufacturing", "small business", "export", "community development block grant", "dislocated worker", "infrastructure"],
        "aln_prefixes": ["17.2", "17.225", "17.207", "17.27", "11.3", "14.228", "59.", "11.020"],
    },
    {
        "id": "deq", "short": "DEQ", "name": "Department of Environmental Quality", "applicant": "state",
        "mission": "Protects North Carolina's air, water and land. Divisions cover air quality, water resources and water infrastructure (Clean Water and Drinking Water State Revolving Funds), waste management and brownfields, coastal management, marine fisheries, energy and mining. Priorities include PFAS and emerging contaminants, coastal resilience, environmental justice and clean energy.",
        "keywords": ["water quality", "drinking water", "wastewater", "stormwater", "air quality", "emissions", "pfas", "contaminant", "brownfield", "superfund", "coastal", "resilience", "wetland", "fisheries", "nonpoint source", "climate", "clean energy", "environmental justice", "solid waste", "recycling"],
        "aln_prefixes": ["66.", "11.4", "81.041", "81.042", "81.254", "15.6"],
    },
    {
        "id": "dhhs", "short": "NCDHHS", "name": "Department of Health and Human Services", "applicant": "state",
        "mission": "Manages health and human services for all North Carolinians: Medicaid, public health, mental health, developmental disabilities and substance use services, child welfare and social services, aging and adult services, child development and early education, vocational rehabilitation, services for the blind and deaf, and state-operated health facilities. Priorities include behavioral health, healthy children and families, and a strong health workforce.",
        "keywords": ["public health", "medicaid", "behavioral health", "mental health", "substance use", "opioid", "maternal", "child health", "child care", "early childhood", "child welfare", "foster care", "aging", "older adults", "disability", "vocational rehabilitation", "food assistance", "nutrition", "immunization", "epidemiology", "health workforce", "rural health"],
        "aln_prefixes": ["93.", "10.557", "10.561", "10.558", "84.126", "84.181", "84.187"],
    },
    {
        "id": "dit", "short": "NCDIT", "name": "Department of Information Technology", "applicant": "state",
        "mission": "Provides statewide IT services, cybersecurity and risk management, and leads broadband expansion and digital equity through the Division of Broadband and Digital Opportunity. Also supports the 911 Board and Next Generation 911, the Center for Geographic Information and Analysis, and government data analytics.",
        "keywords": ["cybersecurity", "cyber", "broadband", "digital equity", "digital inclusion", "internet access", "911", "next generation 911", "geospatial", "gis", "data analytics", "it modernization"],
        "aln_prefixes": ["97.137", "11.035", "11.032", "11.033", "11.034", "20.615", "21.029"],
    },
    {
        "id": "dmva", "short": "DMVA", "name": "Department of Military and Veterans Affairs", "applicant": "state",
        "mission": "Supports veterans and military families through benefits counseling, state veterans homes and state veterans cemeteries, and works with the state's military installations and defense communities on compatible land use, installation resilience and defense industry growth.",
        "keywords": ["veteran", "military", "service member", "military families", "veterans home", "veterans cemetery", "defense community", "installation resilience", "compatible use", "national guard"],
        "aln_prefixes": ["64.", "12.6", "12.617", "12.610"],
    },
    {
        "id": "dncr", "short": "DNCR", "name": "Department of Natural and Cultural Resources", "applicant": "state",
        "mission": "Stewards the state's natural and cultural heritage: state parks and trails, historic sites, state museums, the State Archives and State Library, the Arts Council, the State Historic Preservation Office, the Natural Heritage Program, the North Carolina Zoo, aquariums, and land and water conservation funding.",
        "keywords": ["historic preservation", "museum", "library", "archives", "arts", "humanities", "state parks", "trails", "outdoor recreation", "land conservation", "natural heritage", "cultural resources", "heritage", "zoo", "aquarium", "digitization", "endangered species"],
        "aln_prefixes": ["15.904", "15.916", "15.929", "15.9", "45.", "20.219", "15.6"],
    },
    {
        "id": "dps", "short": "DPS", "name": "Department of Public Safety", "applicant": "state",
        "mission": "Protects North Carolinians through Emergency Management (preparedness, response, recovery and hazard mitigation), the State Highway Patrol, Alcohol Law Enforcement, Juvenile Justice and Delinquency Prevention, and the Governor's Crime Commission, which administers federal justice and victim-services grants.",
        "keywords": ["emergency management", "hazard mitigation", "disaster", "preparedness", "flood", "hurricane", "homeland security", "law enforcement", "juvenile justice", "delinquency prevention", "crime victims", "victim services", "violence against women", "school safety", "public safety"],
        "aln_prefixes": ["97.", "16.575", "16.738", "16.540", "16.588", "16.017", "16.839", "16.034"],
    },
    {
        "id": "dor", "short": "DOR", "name": "Department of Revenue", "applicant": "state",
        "mission": "Administers the state's tax laws, collects revenue that funds state services, and works to detect and prevent tax fraud and identity theft while improving taxpayer service and modernizing tax systems.",
        "keywords": ["tax administration", "revenue", "fraud detection", "identity theft", "taxpayer", "data analytics", "system modernization"],
        "aln_prefixes": ["21."],
    },
    {
        "id": "ncdot", "short": "NCDOT", "name": "Department of Transportation", "applicant": "state",
        "mission": "Plans, builds and maintains the state's highways and bridges and supports public transportation, rail, aviation, ferries, bicycle and pedestrian travel, and ports access. Includes the Division of Motor Vehicles, the Governor's Highway Safety Program and Integrated Mobility. Priorities include safety, resilience, freight mobility and rural connectivity.",
        "keywords": ["transportation", "highway", "bridge", "transit", "rail", "aviation", "airport", "ferry", "bicycle", "pedestrian", "highway safety", "freight", "electric vehicle", "charging", "traffic", "roadway", "rural connectivity"],
        "aln_prefixes": ["20."],
    },
    {
        "id": "ports", "short": "NC Ports", "name": "North Carolina State Ports Authority", "applicant": "state",
        "mission": "Operates the ports of Wilmington and Morehead City and inland terminals, supporting freight movement, port infrastructure modernization, port security and maritime economic growth.",
        "keywords": ["port", "maritime", "freight", "terminal", "port security", "harbor", "dredging", "supply chain", "cargo"],
        "aln_prefixes": ["20.823", "20.8", "97.056"],
    },
    {
        "id": "ncda", "short": "NCDA&CS", "name": "Department of Agriculture and Consumer Services", "applicant": "state",
        "mission": "Supports North Carolina agriculture and protects consumers: food and feed safety, plant and animal health, the NC Forest Service, soil and water conservation, farmland preservation, agricultural marketing and specialty crops, food distribution, and weights and measures.",
        "keywords": ["agriculture", "farm", "farmland", "specialty crop", "food safety", "animal health", "plant health", "pest", "forest", "wildfire", "soil and water conservation", "agricultural marketing", "food distribution", "rural"],
        "aln_prefixes": ["10."],
    },
    {
        "id": "doi", "short": "DOI", "name": "Department of Insurance", "applicant": "state",
        "mission": "Regulates the insurance industry and protects consumers, investigates insurance fraud, and runs the Seniors' Health Insurance Information Program (SHIIP), which counsels Medicare beneficiaries.",
        "keywords": ["insurance", "consumer protection", "insurance fraud", "medicare counseling", "seniors", "health insurance"],
        "aln_prefixes": ["93.324", "93.071"],
    },
    {
        "id": "osfm", "short": "OSFM", "name": "Office of State Fire Marshal", "applicant": "state",
        "mission": "Supports fire and rescue services statewide through firefighter and rescue training, fire prevention and life safety education, building codes and inspections, hazardous materials and urban search and rescue response.",
        "keywords": ["fire", "firefighter", "rescue", "fire prevention", "building code", "hazardous materials", "search and rescue", "life safety", "emergency medical"],
        "aln_prefixes": ["97.044", "97.083", "97.025"],
    },
    {
        "id": "ncdoj", "short": "NCDOJ", "name": "Department of Justice (Attorney General)", "applicant": "state",
        "mission": "Represents the state, protects consumers, supports law enforcement through training at the Justice Academy and criminal justice standards, investigates Medicaid fraud, and addresses opioids, scams, and internet crimes against children.",
        "keywords": ["consumer protection", "law enforcement training", "medicaid fraud", "opioid", "internet crimes against children", "human trafficking", "victim", "elder abuse", "scams"],
        "aln_prefixes": ["16.", "93.775"],
    },
    {
        "id": "sbi", "short": "SBI", "name": "State Bureau of Investigation", "applicant": "state",
        "mission": "Investigates major crimes and supports local law enforcement with criminal intelligence, drug and human-trafficking investigations, cybercrime and digital forensics, and specialized response teams.",
        "keywords": ["criminal investigation", "forensic", "digital forensics", "cybercrime", "drug trafficking", "human trafficking", "intelligence", "law enforcement"],
        "aln_prefixes": ["16.", "95.001"],
    },
    {
        "id": "labor", "short": "NCDOL", "name": "Department of Labor", "applicant": "state",
        "mission": "Protects worker safety and health through the state OSHA plan and free safety consultation, enforces wage and hour laws, inspects elevators, amusement rides and boilers, and promotes mine and quarry safety.",
        "keywords": ["occupational safety", "osha", "workplace safety", "worker health", "wage and hour", "mine safety", "consultation"],
        "aln_prefixes": ["17.503", "17.504", "17.600", "17.5"],
    },
    {
        "id": "dpi", "short": "DPI", "name": "Department of Public Instruction", "applicant": "state",
        "mission": "Supports North Carolina's public schools: K-12 standards and accountability, Title I and other federal education programs, exceptional children and special education, school nutrition, career and technical education, literacy, school safety, educator recruitment and digital learning.",
        "keywords": ["k-12", "school", "students", "teacher", "educator", "literacy", "special education", "title i", "school nutrition", "career and technical education", "school safety", "early learning", "stem", "student mental health"],
        "aln_prefixes": ["84.", "10.553", "10.555", "10.559"],
    },
    {
        "id": "nccc", "short": "NCCCS", "name": "NC Community College System", "applicant": "higher_ed",
        "mission": "Supports the 58 community colleges with workforce training and short-term credentials, adult education and literacy, career and technical education, apprenticeships (ApprenticeshipNC), small business centers and transfer pathways.",
        "keywords": ["community college", "workforce training", "credential", "adult education", "apprenticeship", "career and technical education", "student success", "small business center", "postsecondary"],
        "aln_prefixes": ["84.002", "84.048", "17.2", "17.268", "47.076"],
    },
    {
        "id": "unc", "short": "UNC System", "name": "UNC System (Office and constituent universities)", "applicant": "higher_ed",
        "mission": "Oversees the 17 public universities. Priorities include research and innovation, student access and success, teacher and health workforce preparation, and economic impact across the state, including rural and underserved communities.",
        "keywords": ["research", "university", "higher education", "student success", "innovation", "stem", "teacher preparation", "health workforce", "research infrastructure", "graduate"],
        "aln_prefixes": ["47.", "93.", "81.", "12.", "43.", "84.0"],
    },
    {
        "id": "elections", "short": "NCSBE", "name": "State Board of Elections", "applicant": "state",
        "mission": "Administers elections with the 100 county boards of elections, maintains voter registration systems, and works to secure election infrastructure and improve accessibility.",
        "keywords": ["election", "election security", "voter registration", "voting accessibility", "cybersecurity"],
        "aln_prefixes": ["90.404"],
    },
    {
        "id": "housing", "short": "NCHFA", "name": "NC Housing Finance Agency", "applicant": "state",
        "mission": "Finances affordable housing: rental development, first-time homeownership, home repairs and accessibility modifications, supportive housing, and homelessness prevention, including federal HOME, Housing Trust Fund and housing tax credit programs.",
        "keywords": ["affordable housing", "housing", "homeownership", "rental", "home repair", "homelessness", "supportive housing", "housing trust fund"],
        "aln_prefixes": ["14.239", "14.275", "14.", "21.026"],
    },
    {
        "id": "ncorr", "short": "NCORR", "name": "NC Office of Recovery and Resiliency", "applicant": "state",
        "mission": "Leads long-term disaster recovery and resilience: rebuilding and repairing homes after hurricanes, buyouts and mitigation, infrastructure recovery, and helping communities plan for flooding and climate risks.",
        "keywords": ["disaster recovery", "resilience", "hurricane", "flood", "mitigation", "buyout", "housing recovery", "cdbg-dr", "climate"],
        "aln_prefixes": ["14.228", "14.218", "97.039", "97.047", "97.029"],
    },
    {
        "id": "wildlife", "short": "NCWRC", "name": "Wildlife Resources Commission", "applicant": "state",
        "mission": "Conserves fish and wildlife and their habitats, manages hunting, fishing and boating, enforces wildlife and boating laws, runs boating safety and hunter education, and recovers threatened and endangered species.",
        "keywords": ["wildlife", "fish", "habitat", "hunting", "fishing", "boating", "boating safety", "endangered species", "conservation", "hunter education"],
        "aln_prefixes": ["15.6", "97.012"],
    },
    {
        "id": "aoc", "short": "NCAOC", "name": "Administrative Office of the Courts", "applicant": "state",
        "mission": "Supports the state court system: court technology and eCourts, recovery and treatment courts, court improvement for child welfare cases, Guardian ad Litem, language access, and access to justice.",
        "keywords": ["court", "judicial", "treatment court", "drug court", "guardian ad litem", "child welfare", "language access", "access to justice"],
        "aln_prefixes": ["16.585", "16.", "93.586"],
    },
    {
        "id": "osbm", "short": "OSBM", "name": "Office of State Budget and Management", "applicant": "state",
        "mission": "Prepares the state budget, oversees federal funds compliance, and coordinates statewide grants such as recovery and infrastructure funds; supports data, evaluation and performance management across agencies.",
        "keywords": ["budget", "grants management", "federal funds", "evaluation", "performance management", "data"],
        "aln_prefixes": ["21."],
    },
    {
        "id": "sos", "short": "SOS", "name": "Department of the Secretary of State", "applicant": "state",
        "mission": "Registers businesses and charities, regulates securities and lobbying, commissions notaries, protects investors and consumers from fraud, and maintains land records standards.",
        "keywords": ["business registration", "securities", "investor protection", "fraud", "charities", "notary"],
        "aln_prefixes": [],
    },
    {
        "id": "treasurer", "short": "DST", "name": "Department of State Treasurer", "applicant": "state",
        "mission": "Manages state investments and pension funds, the State Health Plan, unclaimed property, and the Local Government Commission, which oversees local government finances and water and sewer system viability.",
        "keywords": ["local government finance", "water and sewer", "utility viability", "state health plan", "financial literacy"],
        "aln_prefixes": ["21.", "66.458", "66.468"],
    },
    {
        "id": "auditor", "short": "OSA", "name": "Office of the State Auditor", "applicant": "state",
        "mission": "Audits state agencies and programs, including federal Single Audit work, and investigates fraud, waste and abuse.",
        "keywords": ["audit", "fraud", "waste", "abuse", "accountability"],
        "aln_prefixes": [],
    },
]

AGENCY_BY_ID = {a["id"]: a for a in AGENCIES}

# Grants.gov applicant-type codes each kind of NC applicant may apply under.
# 00 State governments | 06 Public/state-controlled institutions of higher education
# 25 Others (see eligibility text) | 99 Unrestricted
ELIGIBILITY_FIT = {
    "state": {"00": 1.0, "99": 1.0, "25": 0.5},
    "higher_ed": {"06": 1.0, "99": 1.0, "25": 0.5},
}


def eligibility_fit(agency: dict, codes: list[str]) -> tuple[float, str]:
    """Return (fit 0-1, human label). 0 means the agency is not eligible and the
    opportunity must be dropped before scoring (strict pre-screen)."""
    table = ELIGIBILITY_FIT[agency["applicant"]]
    best, best_code = 0.0, None
    for c in codes or []:
        if table.get(c, 0) > best:
            best, best_code = table[c], c
    labels = {
        "00": "State governments are eligible",
        "06": "Public universities and colleges are eligible",
        "99": "Open to any applicant",
        "25": "Eligibility listed as 'Others' - check the eligibility text",
    }
    return best, labels.get(best_code, "Not eligible")
