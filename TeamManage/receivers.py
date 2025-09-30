# yourapp/receivers.py
from django.dispatch import receiver
from .signals import (
    contract_extended,
    player_signed,
    player_released,
    player_transferred,
    player_loan_ended,
)
from .news.helpers import create_news_post
from TeamManage.models import NewsPost, Team
from django.contrib.auth import get_user_model
User = get_user_model()


@receiver(contract_extended)
def handle_contract_extended(sender, player, window, user =None, **kwargs):
    if user is None:
        user = User.objects.get(username="FHPL")
    team = Team.objects.filter(user_name=user).first()
    headline = f"{player.first_name} extends contract"
    content = (f"""
        <p>{team} fans have reason to celebrate, as one of the club's brightest stars,
        {player.first_name} {player.last_name} has officially extended his contract with the
        Premier League giants until {window.season} {window.year}.</p>

        <p>The new deal, which will keep the player at the {team} for the foreseeable future,
        marks a significant milestone in the career of the player. It reflects the club's
        confidence in his ability to continue making a meaningful impact on the pitch and
        contribute to the team's ambitions.</p>

        <p>{player.first_name}'s journey with {team} has been nothing short of remarkable. From
        his early days in the youth academy to becoming a regular starter, his dedication and
        hard work have earned him respect from teammates, coaches, and fans alike. His
        performances this season have demonstrated his growth as a player, combining technical
        skill, tactical awareness, and an unyielding competitive spirit.</p>

        <p>Under the guidance of {team.manager_name}, {player.last_name} has developed into a
        versatile and influential figure on the pitch. The manager's possession-based style
        perfectly complements {player.first_name}'s abilities, allowing him to dictate play,
        create scoring opportunities, and contribute defensively when required. His ability to
        read the game and make quick decisions has often turned the tide in critical matches.</p>

        <p>Fans have already expressed their excitement about the contract extension, seeing
        it as a signal of the club's intent to build a team capable of challenging for
        trophies. {player.first_name} is seen not just as a player for today but as a
        cornerstone for the club's future. His leadership qualities, on and off the field,
        have begun to shine, making him a role model for younger squad members and academy
        players.</p>

        <p>Looking ahead, {player.first_name} is expected to take on even greater responsibility
        within the squad, potentially becoming a key figure in the club's pursuit of silverware.
        With his new contract secured, he can focus entirely on his development and helping
        {team} achieve their goals. The club's management and supporters will be hoping that
        this commitment leads to many memorable moments and successes in the years to come.</p>

        <p>In summary, this contract extension represents a win-win situation: the club
        retains a highly talented and committed player, while {player.first_name} gains the
        stability and confidence to continue reaching new heights in his football career.</p>
        """
    )
    title_image = team.logo if team and team.logo else None    
    create_news_post(headline, content, author=None, title_image=title_image)

@receiver(player_signed)
def handle_player_signed(sender, player, team, amount, user = None, **kwargs):
    if user is None:
        user = User.objects.get(username="FHPL")
    headline = f"{player.first_name} {player.last_name} signs for {team.name}"
    content = (f"""
        <p>🚨 Major Transfer Alert: {player.first_name} {player.last_name} has officially signed with {team.name} 
        for a reported fee of {amount}M following a highly competitive bidding war! 🔥</p>
        
        <p>After an intense back-and-forth between multiple top-tier teams, {player.first_name} was courted by a 
        number of suitors, with {team.name} coming out on top as the highest bidder. The bidding process saw 
        several top clubs vying for the star player's signature, but ultimately it was {team.name} that won the race.</p>
        
        <p>Manager {team.manager_name} expressed their excitement at securing the services of such a high-profile player, 
        stating, 'We believe {player.first_name} will be a game-changer for us this season. His quality, experience, 
        and versatility are exactly what we need to strengthen our squad. We can’t wait to see him in action.'</p>
        
        <p>The player is expected to make an immediate impact, and {team.name} fans are eagerly awaiting his debut.
        With {player.first_name}'s track record of goals/assists and exceptional performances, this signing could be
        a major boost for the team as they aim for the top of the league.</p>
        
        <p>On the flip side, {team.name}’s success in the bidding process leaves other interested clubs
        disappointed. These teams will now be looking to adjust their strategies as they look for other transfer targets.</p>
        
        <p>🎯 Fantasy managers, don’t miss out on {player.first_name}. With this high-profile move, he’s bound to be a
        key figure for {team.name}, and could be a great addition to your fantasy team this season!</p>
        """
    )
    title_image = team.logo if team and team.logo else None
    create_news_post(headline, content, author=None, title_image=title_image)

@receiver(player_released)
def handle_player_released(sender, player, team, user, contract_expiry, **kwargs):
    if user is None:
        user = User.objects.get(username="FHPL")
    headline = f"{player.first_name} {player.last_name} released from {team.name}"
    content = (f"""
        <p>{player.first_name} {player.last_name} Becomes a Free Agent After Contract Expires with {team.name}</p>

        <p>In a significant move within the world of football, <{player.first_name} {player.last_name}, who had been a key figure for {team.name} until the conclusion of their contract, has officially become a free agent. The player’s agreement with the club expired at the close of the {contract_expiry.season} {contract_expiry.year} transfer window.</p>

        <p>{team.name} released a statement confirming that {player.last_name} is now eligible to explore opportunities with other teams, either through direct negotiations or by entering the upcoming free agent bidding process. This marks a new chapter in the player’s career, with speculation already circulating about potential destinations for the talented player like him.</p>

        </p>During their time at {team.name}, {player.last_name} proved to be an invaluable asset, making numerous contributions both on and off the pitch. Over the course of their tenure, the player notched up impressive statistics, including, cementing their place as one of the club's standout performers.</p>

        <p>In response to the player’s departure, {team.name} expressed gratitude for {player.last_name}’s efforts and dedication, with the club’s management commenting: “We would like to extend our sincere thanks to {player.last_name} for their commitment and hard work during their time with us. We wish them all the best in their future endeavors and look forward to following their career with interest.”</p>

        <p>In the wake of {player.last_name}’s departure, {team.name}’ boss {team.manager_name}, shared a thoughtful message reflecting on the player’s time at the club. The manager emphasized that while the departure is a loss for the team, the club remains focused on building for the future and will continue to strengthen the squad in anticipation of the upcoming season.</p>

        <p>As a free agent, {player.last_name} is now open to discussing terms with potential suitors, and it remains to be seen which team will be the next to secure their services. Fans and pundits alike will be watching closely as the transfer market heats up.</p>
        """
    )
    create_news_post(headline, title_image=team.logo, content = content, author=None)

@receiver(player_transferred)
def handle_player_transferred(sender, player, from_team, to_team, amount, user = None, is_loan = False, loan_gameweek=None, **kwargs):
    if user is None:
        user = User.objects.get(username="FHPL")
    team = Team.objects.filter(user_name=user).first()
    if is_loan:
        headline = f"{player.first_name} {player.last_name} joins {to_team.name} on loan"
        content = (f"""
            <p>🔁 Loan Deal Confirmed: {player.first_name} {player.last_name} has completed a temporary move from 
            {from_team.name} to {to_team.name} on loan until Gameweek {loan_gameweek}. 🤝</p>

            <p>The deal, valued at {amount}M, allows {to_team.name} to strengthen their squad with a quality player 
            without a permanent commitment, while {from_team.name} looks to give {player.first_name} valuable playing time.</p>

            <p>{to_team.manager_name}, the manager of {to_team.name}, commented on the move, saying,
            '{player.first_name} brings a lot of energy and creativity to our lineup. We’re confident he’ll contribute significantly 
            during this loan spell.</p>

            <p>{player.first_name} will return to {from_team.name} at the end of Gameweek {loan_gameweek}, and the parent club
            will be monitoring his progress closely during the loan period.</p>

            <p>🎯 For fantasy managers, this loan spell might offer short-term value — especially if {player.last_name} hits form in the coming weeks.
            Keep an eye on his performances while he's wearing the {to_team.name} colors!</p>
            """
        )
    else:
        headline = f"{player.first_name} {player.last_name} transfers to {to_team.name}"
        content = (f"""
            <p>🚨 Transfer News: {player.first_name} {player.last_name} has completed a move from {from_team.name}
            to {to_team.name} for a reported fee of {amount} million. 🌟</p>
            
            <p>{player.first_name} joins {to_team.name} after a successful stint at {from_team.name}, where
            he played under {from_team.manager_name}. The move is seen as a strategic one, with {to_team.name}
            looking to bolster their squad ahead of the upcoming season.</p>
            
            <p>Manager {to_team.manager_name} will be hoping {player.first_name} can bring his skills to the table 
            as they push for the top positions in the league. The deal is expected to provide {to_team.name} 
            with a more dynamic and versatile attacking option.</p>
            
            <p>In return, {from_team.name}, managed by {from_team.manager_name}, will be looking to reinvest the
            money into strengthening other areas of their team. {from_team.user_name} will now be on the lookout
            for new recruits to fill the void left by {player.first_name}'s departure.</p>
            
            <p>Fantasy managers, keep an eye on this player in the coming weeks, as he could be a game-changer
            for {to_team.name}!</p>
            """
            )

    title_image = to_team.logo if team and team.logo else None
    create_news_post(headline, content, author=None, title_image=title_image)

@receiver(player_loan_ended)
def handle_player_loan_ended(sender, player, from_team, to_team, amount, user = None, is_loan = False, loan_gameweek=None, **kwargs):
    if user is None:
        user = User.objects.get(username="FHPL")
    team = Team.objects.filter(user_name=user).first()
    
    headline = f"{player.first_name} {player.last_name} back to {to_team.name} after loan"
    content = (f"""
        <p>🔁 Loan Deal Confirmed: {player.first_name} {player.last_name} has completed a temporary move from 
        {from_team.name} to {to_team.name} on loan until Gameweek {loan_gameweek}. 🤝</p>

        <p>The deal, valued at {amount}M, allows {to_team.name} to strengthen their squad with a quality player 
        without a permanent commitment, while {from_team.name} looks to give {player.first_name} valuable playing time.</p>

        <p>{to_team.manager_name}, the manager of {to_team.name}, commented on the move, saying,
        '{player.first_name} brings a lot of energy and creativity to our lineup. We’re confident he’ll contribute significantly 
        during this loan spell.</p>

        <p>{player.first_name} will return to {from_team.name} at the end of Gameweek {loan_gameweek}, and the parent club
        will be monitoring his progress closely during the loan period.</p>

        <p>🎯 For fantasy managers, this loan spell might offer short-term value — especially if {player.last_name} hits form in the coming weeks.
        Keep an eye on his performances while he's wearing the {to_team.name} colors!</p>
        """
        )
    title_image = to_team.logo if team and team.logo else None
    create_news_post(headline, content, author=None, title_image=to_team.logo)

    

