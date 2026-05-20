"""
classifier.py — Core ICT Job Classification Engine.
Implements a two-pass regex system:
1. Pass 1: Positive match against 14 ICT categories.
2. Pass 2: Post-exclusion of false positives (Medical, Academic, etc.).
"""

import re

# ─── Configuration ────────────────────────────────────────────────────────────

# Priority order for category assignment (Priority Waterfall)
ICT_CATEGORIES = [
    "Cybersecurity & GRC",
    "Cloud, Infrastructure & DevOps",
    "AI, Data & Analytics",
    "Software Development",
    "IT Leadership & Management",
    "IT Support & Helpdesk",
    "Networking & Telecom",
    "ERP & Enterprise Apps",
    "Pre-Sales & Solutions Architecture",
    "PM, Agile & Product",
    "UI/UX & Product Design",
    "RPA & Automation",
    "QA & Testing",
    "Other ICT"
]

# ─── Patterns ─────────────────────────────────────────────────────────────────

# Pass 1: Positive ICT Match Patterns
# Each pattern uses \b word boundaries to prevent substring false positives.
ICT_PATTERNS = {
    "Software Development": [
        r'software', r'developer', r'full-stack', r'front-end', r'back-end', 
        r'javascript', r'java', r'python', r'react', r'angular', r'vue', 
        r'node\.js', r'\.net', r'c\+\+', r'c#', r'golang', r'ruby', r'swift', 
        r'kotlin', r'flutter', r'mobile app', r'mobile developer', 
        r'iOS developer', r'android developer', r'PHP', r'laravel', 
        r'django', r'spring boot', r'programmer', r'API developer', 
        r'microservices', r'SaaS', r'SDK', r'web developer', 
        r'embedded software', r'embedded system', r'embedded engineer', 
        r'firmware', r'tech lead', r'outsystems',
        r'typescript', r'rust', r'graphql',
    ],
    "Cybersecurity & GRC": [
        r'cybersecurity', r'infosec', r'information security', r'IT security', 
        r'security (engineer|analyst|architect|consultant|manager|officer|specialist|operations)', 
        r'CISO', r'SOC analyst', r'SOC engineer', r'SOC manager', 
        r'incident response', r'threat (intel|hunt|analyst)', 
        r'penetration test', r'vulnerability', r'ethical hack', r'red team', 
        r'blue team', r'malware analyst', r'GRC', r'IT risk', r'IT audit', 
        r'IT compliance', r'ISO 27001', r'NIST', r'PCI-DSS', r'data privacy', 
        r'GDPR', r'DPO', r'data protection officer', r'IAM', 
        r'identity access management', r'privileged access', r'zero trust', 
        r'SIEM', r'Splunk', r'Sentinel', r'QRadar', r'SOAR', r'EDR', r'XDR', 
        r'firewall', r'WAF', r'DLP', r'devsecops', r'cryptography',
        r'soc (l1|l2|l3|lead|ops|operations|team lead)',
        r'purple team(ing)?', r'cism', r'nca (ecc|dcc)',
        r'cyber.*pre.?sales', r'cybersecurity (sales|pre.?sales)',
        r'penetration tester', r'penetration testing',
    ],
    "Cloud, Infrastructure & DevOps": [
        r'cloud (architect|engineer|admin|specialist|migration|consultant|manager|security|platform)', 
        r'AWS', r'Azure', r'GCP', r'Google Cloud', r'VMware', r'virtualization', 
        r'DevOps', r'site reliability', r'SRE', r'CI/CD', r'Jenkins', 
        r'Terraform', r'Ansible', r'Kubernetes', r'K8s', r'Docker', 
        r'containerization', r'GitOps', 
        r'infrastructure (engineer|manager|architect|specialist|admin|lead)', 
        r'sysadmin', r'system admin', r'systems engineer', r'Linux (engineer|admin)', 
        r'Windows (server|admin|engineer)', r'Unix', r'server (engineer|admin|manager)', 
        r'Active Directory', r'Exchange admin', r'M365', 
        r'storage (engineer|admin|architect)', r'backup (engineer|admin)', 
        r'data center (engineer|manager|architect|specialist|technician)', 
        r'system architect', r'system analyst',
        r'cloud (expert|ops|finops|networking|sales|advisor)',
        r'it infrastructure (engineer|manager|project manager|specialist|technician|support)',
        r'infrastructure.?(cloud|security) (lead|engineer|manager|transform)',
        r'openshift', r'red hat',
        r'linux (administrator|system|kernel|systems)',
        r'infra.?as.?code', r'multicloud', r'systems architect',
        r'cloud.*transform',
    ],
    "AI, Data & Analytics": [
        r'artificial intelligence', r'machine learning', r'deep learning', 
        r'NLP', r'natural language', r'computer vision', r'neural', r'LLM', 
        r'GenAI', r'generative AI', r'agentic AI', 
        r'AI (engineer|architect|specialist|researcher|lead|manager|consultant|product|platform|agent|trainer)', 
        r'chief AI', r'data (scientist|engineer|analyst|architect|modeler|warehouse|pipeline|lake|governance|steward|quality|integration|migration|platform|visualization|automation|intelligence|lead|management|strategy)', 
        r'big data', r'Hadoop', r'Spark', r'Kafka', r'Airflow', r'Snowflake', 
        r'Databricks', r'Redshift', r'BigQuery', r'ETL', r'ELT', 
        r'business intelligence', r'BI (developer|analyst|engineer)', 
        r'Power BI', r'Tableau', r'Qlik', r'Looker', r'SQL developer', 
        r'database (admin|developer|engineer|architect|DBA)', 
        r'Oracle (developer|DBA|admin)', r'MySQL', r'PostgreSQL', 
        r'MongoDB', r'NoSQL', r'Redis', r'Cassandra', 
        r'ML (engineer|ops|developer|scientist)', r'MLOps', r'DataOps',
        r'ai (automation|deployment|governance|implementation|innovation|engagement|operations|support|security|strategy|success|research|search|design lead|systems architect|tester|video|project manager|pm|solutions sales|platform sales)',
        r'ai.?for.?chip', r'ai/ml', r'data.?&.?ai', r'engineering ai', r'ai.?&.?data',
        r'dba', r'mssql', r'sql (dba|database admin|database administrator)',
        r'calypso', r'murex', r'odoo', r'finacle', r't24', r'temenos',
        r'copilot (engineer|specialist|expert|architect)', r'ai solution architect',
        r'data cloud',
    ],
    "Networking & Telecom": [
        r'network (engineer|admin|architect|specialist|analyst|manager|technician|consultant|security|operations|lead|director)', 
        r'Cisco', r'CCNA', r'CCNP', r'CCIE', r'Juniper', r'Palo Alto', 
        r'Fortinet', r'FortiGate', r'F5', r'Checkpoint', r'Meraki', 
        r'NOC (engineer|analyst|technician|manager)', r'telecom', 
        r'telecommunications', r'5G', r'fiber optic', r'VoIP', 
        r'unified communications', r'IP telephony', 
        r'wireless (engineer|architect|specialist)', r'SD-WAN', r'MPLS', 
        r'BGP', r'OSPF',
        r'wan engineer', r'lan engineer', r'cloud networking',
    ],
    "ERP & Enterprise Apps": [
        r'SAP', r'ABAP', r'HANA', r'FICO', r'MM', r'SD', r'PP', r'Basis', 
        r'BW', r'BO', r'CRM', r'Ariba', r'EWM', r'GTS', r'SRM', 
        r'Oracle (EBS|Fusion|Apps|ERP|HCM|SCM|Financials)', r'ERP', 
        r'Dynamics 365', r'D365', r'Navision', r'Business Central', 
        r'Workday', r'PeopleSoft', r'NetSuite', r'Salesforce', r'SFDC', 
        r'Apex developer', r'MuleSoft', r'Veeva', r'ServiceNow', r'ITSM', 
        r'ITIL', r'SharePoint', r'Power Platform', r'Power Automate', 
        r'Power Apps', r'CRM (developer|admin|consultant|manager|specialist|analyst)', 
        r'enterprise architect', r'enterprise architecture', 
        r'application (analyst|architect|engineer|manager|specialist|support|operations)', 
        r'Outsystems',
        r'odoo', r'finacle', r'murex', r'calypso', r't24', r'temenos',
        r'erp sales', r'sap sales', r'oracle cloud',
    ],
    "IT Support & Helpdesk": [
        r'IT support', r'helpdesk', r'help desk', r'desktop support', 
        r'technical support (engineer|specialist|analyst|technician|agent|lead|manager)', 
        r'service desk', r'IT (officer|coordinator|assistant|administrator|admin|executive|technician|technical|engineer|specialist|consultant)', 
        r'desktop (engineer|technician|admin)', r'computer (hardware|technician)', 
        r'information technology (technician|engineer|manager|consultant|service)', 
        r'IT business analyst'
    ],
    "IT Leadership & Management": [
        r'CTO', r'CIO', r'chief (technology|information|digital|data) officer', 
        r'IT (manager|director|head|lead|VP)', r'technology (manager|director|head|lead|officer)', 
        r'head of (IT|technology|engineering|software|data|cyber|information security|information technology|platform|AI|digital)', 
        r'VP of (engineering|technology|IT|software|data|product|digital)', 
        r'director of (IT|technology|engineering|software|data|cyber|information|digital|product|AI|fintech)', 
        r'software engineering manager', r'AI/ML engineering manager'
    ],
    "Pre-Sales & Solutions Architecture": [
        r'pre-sales (engineer|consultant|manager|specialist|architect|lead|director)', 
        r'solutions (architect|engineer|consultant|designer|specialist|manager|lead|director)', 
        r'technical (architect|consultant|lead|specialist|advisor|account manager|implementation|strategy)', 
        r'creative technologist', r'design technologist', r'marketing technologist'
    ],
    "PM, Agile & Product": [
        r'IT project manager', r'technical project manager', 
        r'software project manager', r'scrum master', 
        r'agile (coach|lead|manager)', r'product owner', 
        r'release manager', r'delivery manager', 
        r'product manager (tech|IT|software|digital|platform|AI|crypto|fintech|CRM|SaaS|payment|mobile|API|data|cloud|gaming)', 
        r'technical product manager', r'technical program manager', 
        r'digital transformation (consultant|specialist|lead|manager)', 
        r'digital (delivery|project|program) (lead|manager|specialist)',
        r'agile (product|program|project) (manager|lead)',
        r'scrum of scrums', r'tech pm', r'ai project manager',
    ],
    "UI/UX & Product Design": [
        r'UI/UX', r'UX/UI', r'user experience', r'user interface', 
        r'UX (design|research|writer|strategist|engineer)', 
        r'UI (design|developer|engineer|lead)', r'interaction design', 
        r'information architect', r'usability', r'Figma', r'Adobe XD', 
        r'web designer', r'design system (designer|manager|specialist)'
    ],
    "RPA & Automation": [
        r'RPA', r'robotic process automation', r'UiPath', r'Blue Prism', 
        r'Automation Anywhere', r'Power Automate', 
        r'automation (engineer|developer|architect|specialist|analyst|manager|lead|tester|test|expert)', 
        r'test automation'
    ],
    "QA & Testing": [
        r'QA (engineer|analyst|lead|manager|tester|automation|manual)', 
        r'quality assurance (software|IT|test|automation)', r'SDET', 
        r'software (test|quality)', r'test (engineer|analyst|lead|manager|architect)', 
        r'Selenium', r'Cypress', r'Appium', r'JMeter', r'LoadRunner', 
        r'Postman', r'API test', r'UAT specialist',
        r'junior testing engineer', r'deployment.*testing',
        r'qa testing engineer', r'vfd testing',
    ],
    "Other ICT": [
        r'blockchain', r'smart contract', r'Solidity', r'Web3', r'DeFi', 
        r'crypto (developer|engineer)', r'fintech (specialist|support)', 
        r'IoT', r'internet of things', 
        r'robotics (engineer|developer|programmer|software)', r'digital twin', 
        r'technical writer', r'IT procurement', 
        r'e-commerce (manager|director|specialist|product|technical)', 
        r'GIS (analyst|specialist)', r'platform (engineer|architect|specialist)', 
        r'technology (analyst|auditor|consultant|integration|project)', 
        r'business analyst (IT|tech|system|SAP|Oracle)', 
        r'integration (architect|engineer|specialist|manager|lead|consultant)',
        r'scada (engineer|operator|specialist|architect|and plc)',
        r'plc (engineer|specialist|technician|programmer|automation)',
        r'kong api', r'liferay', r'web methods', r'platform screen door',
        r'software sales', r'it infrastructure sales',
        r'vfd (engineer|repair|testing)', r'embedded hardware',
        r'ot (penetration|security)',
    ]
}

# Pass 2: Post-Exclusion Patterns (False Positive Removal)
EXCLUSION_PATTERNS = [
    # Medical/clinical
    r'clinical coder', r'medical coding', r'coding instructor',
    # Design (non-digital)
    r'graphic designer', # Unless UI/UX/App context, handled by priority
    # Academic (scoped: allow ICT teaching titles)
    r'(lecturer|professor|faculty|adjunct)(?!.*\b(cybersecurity|ai|software|data science|computer science|it|ict)\b)',
    r'teaching faculty',
    # Financial (unless tech context)
    r'financial analyst', r'financial planning', r'financial operations',
    r'investment analyst', r'tax analyst', r'credit analyst', r'treasury analyst',
    # Digital non-IT
    r'digital marketing', r'social media', r'digital (sales|content|media|print|style|pharmacist|writer|range|paid|advertising|commercial|communications)',
    # Community roles
    r'community (manager|coordinator|officer|executive|specialist|engagement)',
    # Geotechnical
    r'geotechnical',
    # Data entry
    r'data entry', r'data (collector|feeder|capture)', r'field data collection',
    # Non-IT servers
    r'banquet server', r'food server', r'shisha server', r'lead server', r'F&B server',
    # Construction technical
    r'technical (engineer|manager|coordinator|supervisor|director|inspector|assistant) (construction|civil|interior|structural|joinery|fit-out|MEP|mechanical|HVAC|marine|aviation|automotive|NDT|fire|building|site|urban|hospital)',
    # Technical sales/marketing
    r'technical sales', r'technical marketing',
    # Generic sales
    r'sales (engineer|executive|manager|associate|coordinator|officer|specialist|representative|consultant)',
    # Non-IT robotics
    r'robotic (operator|repair|technician)', r'robotics trainer',
    # Non-IT transformation
    r'transformation (manager|lead|specialist|officer|consultant)',
    # Non-IT product
    r'product specialist', r'product analyst',
    # Digital printing/operations
    r'digital (printing|operation incharge|asset librarian)',
    # Freelance evaluation roles
    r'freelance (AI evaluation|data science|English writer|junior journalist|machine learning|reporter)'
]

# ─── Compiled Regexes ────────────────────────────────────────────────────────

# Compile ICT patterns into a mapping of Category -> List of Regex objects
COMPILED_ICT_PATTERNS = {}
for category, patterns in ICT_PATTERNS.items():
    compiled_list = []
    for p in patterns:
        # Each pattern uses \b word boundaries
        regex_str = rf'\b{p}\b'
        compiled_list.append(re.compile(regex_str, re.IGNORECASE))
    COMPILED_ICT_PATTERNS[category] = compiled_list

# Compile exclusion patterns
COMPILED_EXCLUSIONS = [re.compile(rf'\b{p}\b', re.IGNORECASE) for p in EXCLUSION_PATTERNS]


# ─── Core Classification Functions ───────────────────────────────────────────

def classify_job(title: str) -> tuple[bool, str | None]:
    """
    Classify a job title as ICT or non-ICT.
    Returns: (is_ict: bool, category: str | None)
    """
    if not title:
        return False, None

    title_clean = title.strip()

    # Pass 1: Positive ICT Match
    # We check in priority order defined by ICT_CATEGORIES
    matched_category = None
    for category in ICT_CATEGORIES:
        patterns = COMPILED_ICT_PATTERNS.get(category, [])
        for regex in patterns:
            if regex.search(title_clean):
                matched_category = category
                break
        if matched_category:
            break

    if not matched_category:
        return False, None

    # Pass 2: Post-Exclusion (False Positive Removal)
    # Exceptions: If the job matches priority categories like UI/UX or AI, 
    # we might want to skip some exclusions, but the SRD says Pass 2 runs AFTER Pass 1.
    for regex in COMPILED_EXCLUSIONS:
        if regex.search(title_clean):
            # Special check: certain exclusions shouldn't apply if specific high-priority keywords are present
            # e.g. "Digital Marketing Manager" is excluded, but "Digital Transformation Lead" might be matched in PM.
            # The SRD mentions "unless IT/tech/digital/AI context" for some exclusions.
            # To strictly follow SRD: "If any exclusion matches, the job is reclassified as non-ICT."
            return False, None

    return True, matched_category


def get_ict_stats(jobs: list[dict]) -> dict:
    """
    Calculate summary statistics for a list of jobs.
    """
    total = len(jobs)
    ict_jobs = [j for j in jobs if j.get('_is_ict')]
    ict_count = len(ict_jobs)
    
    category_breakdown = {}
    for j in ict_jobs:
        cat = j.get('ict_category', 'Other ICT')
        category_breakdown[cat] = category_breakdown.get(cat, 0) + 1

    return {
        "total_scraped": total,
        "total_ict": ict_count,
        "ict_rate": round((ict_count / total * 100), 2) if total > 0 else 0,
        "categories": category_breakdown
    }
