"""Sample datasets for summarization evaluation template."""

from typing import Any, Dict, List


def get_summarization_samples() -> List[Dict[str, Any]]:
    """Get sample summarization dataset for testing and demonstration."""
    return [
        {
            "input": """
Artificial Intelligence (AI) has rapidly evolved from a niche academic field to a transformative technology reshaping industries worldwide. The current AI revolution is driven primarily by advances in deep learning, increased computational power, and the availability of massive datasets. Machine learning algorithms, particularly neural networks, have achieved remarkable breakthroughs in areas such as computer vision, natural language processing, and game playing.

The impact of AI extends across numerous sectors. In healthcare, AI systems assist in medical diagnosis, drug discovery, and personalized treatment plans. The financial industry utilizes AI for fraud detection, algorithmic trading, and risk assessment. Transportation is being revolutionized by autonomous vehicles and intelligent traffic management systems. In education, AI enables personalized learning experiences and automated grading systems.

However, the rapid advancement of AI also presents significant challenges. Ethical concerns include bias in AI systems, privacy issues, and the potential displacement of human workers. There are ongoing debates about AI transparency, accountability, and the need for regulatory frameworks. Additionally, the concentration of AI capabilities in a few large technology companies raises concerns about market dominance and equitable access to AI benefits.

Looking forward, the future of AI holds both tremendous promise and uncertainty. Emerging areas such as quantum computing, neuromorphic chips, and artificial general intelligence (AGI) could lead to even more profound changes. Society must navigate the balance between harnessing AI's potential for human benefit while mitigating its risks through thoughtful governance, ethical guidelines, and inclusive development practices.
            """.strip(),
            "expected_output": "AI has evolved from an academic field to a transformative technology driving change across healthcare, finance, transportation, and education through advances in deep learning and neural networks. While offering significant benefits like medical diagnosis assistance and personalized learning, AI presents challenges including bias, privacy concerns, job displacement, and market concentration among tech giants. The future promises further breakthroughs in quantum computing and AGI, requiring careful balance between innovation and risk mitigation through ethical governance.",
            "source_type": "article",
            "target_length": "short",
            "summary_type": "abstractive",
        },
        {
            "input": """
The global climate crisis continues to intensify as greenhouse gas concentrations reach unprecedented levels. According to the latest IPCC report, atmospheric CO2 levels have surpassed 415 parts per million, the highest in over 3 million years. This increase is primarily attributed to human activities, including fossil fuel combustion, deforestation, and industrial processes.

The consequences of climate change are becoming increasingly visible worldwide. Rising global temperatures have led to more frequent and severe heatwaves, droughts, and extreme weather events. Arctic ice sheets are melting at accelerating rates, contributing to sea-level rise that threatens coastal communities. Ocean acidification, caused by increased CO2 absorption, is damaging marine ecosystems and coral reefs.

International efforts to address climate change have centered around the Paris Agreement, which aims to limit global warming to well below 2°C above pre-industrial levels. However, current national commitments fall short of this target. Many countries have announced net-zero emission goals, but implementation remains challenging due to economic, political, and technological barriers.

Potential solutions include transitioning to renewable energy sources, improving energy efficiency, developing carbon capture technologies, and implementing carbon pricing mechanisms. Nature-based solutions such as reforestation and wetland restoration also play crucial roles. Success requires unprecedented global cooperation, significant financial investment, and rapid technological innovation across all sectors of the economy.
            """.strip(),
            "expected_output": "The climate crisis has reached critical levels with CO2 concentrations at 415 ppm, causing rising temperatures, extreme weather, ice sheet melting, and ocean acidification. While the Paris Agreement targets limiting warming to 2°C, current commitments are insufficient. Solutions include renewable energy transition, carbon capture, pricing mechanisms, and nature-based approaches, but require global cooperation and significant investment to implement effectively.",
            "source_type": "news",
            "target_length": "medium",
            "summary_type": "abstractive",
        },
        {
            "input": """
The meeting was called to order at 2:00 PM by CEO Sarah Johnson. Present were CFO Michael Chen, CTO Lisa Rodriguez, VP Marketing David Kim, and VP Operations Emily Wang. The agenda focused on Q3 performance review and Q4 planning.

Financial Performance: CFO Chen reported Q3 revenue of $2.4M, exceeding target by 12%. Operating expenses remained within budget at $1.8M. Net profit margin improved to 25%, up from 18% in Q2. The company maintained strong cash flow with $800K in reserves.

Technical Updates: CTO Rodriguez announced the successful launch of the mobile app beta, with 500 active testers. The new API integration is 80% complete and on track for October release. Two critical security patches were implemented without downtime.

Marketing Results: VP Kim presented campaign metrics showing 35% increase in web traffic and 28% improvement in conversion rates. The recent partnership with TechCorp generated 150 qualified leads. Social media engagement grew by 45% across all platforms.

Operations Report: VP Wang noted supply chain improvements reduced delivery times by 20%. Customer satisfaction scores increased to 4.2/5.0. The team successfully hired 3 new engineers and 2 support staff.

Action Items: 1) Finalize Q4 budget by October 15 (Chen), 2) Complete API integration testing (Rodriguez), 3) Launch holiday marketing campaign (Kim), 4) Prepare annual employee reviews (Wang).

Meeting adjourned at 3:30 PM. Next meeting scheduled for November 1st.
            """.strip(),
            "expected_output": "The executive team met to review Q3 performance and plan Q4. Key highlights: revenue of $2.4M exceeded targets by 12% with 25% profit margin; mobile app beta launched with 500 testers; marketing campaigns increased web traffic 35% and conversions 28%; operations improved delivery times 20% and customer satisfaction to 4.2/5. Action items assigned for Q4 budget, API testing, holiday campaigns, and employee reviews.",
            "source_type": "meeting_notes",
            "target_length": "medium",
            "summary_type": "extractive",
        },
        {
            "input": """
Subject: Project Alpha Status Update

Dear Team,

I wanted to provide an update on Project Alpha's progress and address some concerns raised in yesterday's stakeholder meeting.

Current Status:
We have completed 75% of the development phase, which puts us slightly ahead of schedule. The core functionality has been implemented and tested. However, we encountered unexpected challenges with the third-party API integration that may impact our timeline.

Technical Issues:
The API provider changed their authentication protocol without sufficient notice, requiring our team to refactor the integration layer. Our senior developer estimates this will add 1-2 weeks to the development timeline. We've escalated this issue with the vendor and are exploring alternative solutions.

Budget Impact:
Due to the additional development time, we anticipate a 15% budget overrun, approximately $50,000. This includes overtime costs and potential contractor fees. I've prepared a detailed cost breakdown for management review.

Risk Mitigation:
To minimize delays, we've implemented parallel development tracks and brought in a consultant specialist in API integrations. We're also preparing a contingency plan that removes non-essential features if necessary.

Next Steps:
1. Complete API integration by end of next week
2. Begin comprehensive testing phase
3. Prepare deployment strategy
4. Schedule client demonstration

I'll provide another update next Friday. Please let me know if you have any questions or concerns.

Best regards,
Alex Thompson
Project Manager
            """.strip(),
            "expected_output": "Project Alpha is 75% complete and ahead of schedule, but faces challenges with third-party API integration due to unexpected authentication protocol changes. This may add 1-2 weeks and cause a 15% budget overrun ($50k). The team is implementing parallel development, consulting specialists, and preparing contingency plans to minimize delays while working toward API completion and testing phases.",
            "source_type": "email",
            "target_length": "short",
            "summary_type": "abstractive",
        },
    ]


def get_news_summarization_samples() -> List[Dict[str, Any]]:
    """Get sample news summarization dataset."""
    return [
        {
            "input": """
LONDON - The Bank of England raised interest rates by 0.25 percentage points to 5.25% on Thursday, marking the 14th consecutive increase since December 2021. The decision was made in response to persistent inflation pressures, with the Consumer Price Index remaining at 6.8% in July, well above the central bank's 2% target.

Governor Andrew Bailey stated that the Monetary Policy Committee voted 6-3 in favor of the rate hike, with three members advocating for a more aggressive 0.5 percentage point increase. "While there are signs that inflationary pressures are beginning to ease, we must remain vigilant and committed to bringing inflation back to our target," Bailey said during a press conference.

The rate increase has immediate implications for mortgage holders, with analysts predicting that average mortgage rates could reach 6.5% by the end of the year. This would affect approximately 1.4 million households due to refinance their mortgages in 2024. Housing market experts warn that this could lead to a significant cooling in property prices, with some forecasting declines of up to 10% over the next 18 months.

Financial markets reacted negatively to the news, with the FTSE 100 falling 1.2% in morning trading. The pound strengthened against the dollar, reaching $1.27, its highest level in three months. Several major banks immediately announced increases to their lending rates, with Barclays and HSBC raising their prime rates within hours of the announcement.
            """.strip(),
            "expected_output": "The Bank of England raised interest rates to 5.25%, the 14th consecutive increase since 2021, to combat inflation remaining at 6.8%. The 6-3 committee vote could push mortgage rates to 6.5%, affecting 1.4 million households and potentially causing 10% property price declines. Markets fell 1.2% while the pound rose to $1.27, and major banks immediately increased their lending rates.",
            "source_type": "news",
            "target_length": "short",
            "summary_type": "abstractive",
        }
    ]


def get_technical_summarization_samples() -> List[Dict[str, Any]]:
    """Get sample technical document summarization dataset."""
    return [
        {
            "input": """
This research paper presents a novel approach to improving neural network efficiency through dynamic pruning techniques. Traditional static pruning methods remove connections based on predetermined criteria, but our dynamic approach adapts the network structure during training based on real-time performance metrics.

Methodology: We implemented a gradient-based pruning algorithm that monitors connection importance throughout the training process. Connections with consistently low gradient magnitudes over a sliding window of 100 iterations are marked for removal. The pruning threshold is adjusted automatically based on validation accuracy to maintain performance while maximizing compression.

Experimental Setup: We evaluated our approach on three benchmark datasets: CIFAR-10, ImageNet, and a custom text classification dataset. Five different network architectures were tested: ResNet-50, VGG-16, BERT-base, and two custom CNN designs. Training was performed using Adam optimizer with learning rates ranging from 0.001 to 0.1.

Results: Our dynamic pruning method achieved an average model size reduction of 73% while maintaining 97.2% of original accuracy. Compared to static pruning methods, our approach showed 15% better compression ratios and 8% faster inference times. Memory usage decreased by 68% on average across all tested configurations.

The technique showed particular effectiveness on larger models, with ResNet-50 achieving 78% size reduction and BERT-base reaching 71% compression. Interestingly, some models experienced slight accuracy improvements due to the regularization effect of dynamic pruning.

Limitations include increased training time (approximately 20% longer) and the need for careful hyperparameter tuning. Future work will explore adaptive threshold mechanisms and integration with other compression techniques such as quantization.
            """.strip(),
            "expected_output": "This paper introduces a dynamic neural network pruning method that adapts network structure during training based on gradient magnitudes. Testing on CIFAR-10, ImageNet, and text datasets with ResNet-50, VGG-16, and BERT models achieved 73% average size reduction while maintaining 97.2% accuracy. The approach outperformed static pruning with 15% better compression and 8% faster inference, though requiring 20% longer training time.",
            "source_type": "research_paper",
            "target_length": "medium",
            "summary_type": "abstractive",
        }
    ]
