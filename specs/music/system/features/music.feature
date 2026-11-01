Feature: SPEC-MUSIC-001 music recommendation
  Step bindings must be implemented before execution.

  @TC-M-001
  Scenario: Register and login with CSRF
    Given an unused username and a valid CSRF token
    When I POST valid credentials to "/api/v1/auth/register/"
    Then the status is 201 and onboarding_completed is false
    When I POST those credentials to "/api/v1/auth/login/"
    Then the status is 200 and a session cookie is set

  @TC-M-002
  Scenario: Deny cross-user playlist access
    Given user 1 owns playlist 10 and user 2 is authenticated
    When user 2 GETs "/api/v1/playlists/10/"
    Then the status is 404 and the playlist is unchanged

  @TC-M-003
  Scenario Outline: Initialize preferences
    Given I am authenticated and tags 1 to 5 are active
    When I PUT tag_ids <tags> to "/api/v1/me/interests/"
    Then the status is <status>
    Examples:
      | tags    | status |
      | [1,2,3] | 200    |
      | []      | 200    |
      | [1]     | 400    |
      | [1,1,2] | 400    |

  @TC-M-004
  Scenario: Stream licensed media only
    Given song 1 has verified playable media and I am logged in
    When I GET "/api/v1/songs/1/stream/" with Range "bytes=0-99"
    Then the status is 206 with 100 audio bytes
    When song 1 loses playback permission
    Then its stream returns 403 without audio bytes

  @TC-M-005
  Scenario: Idempotent favorite and membership
    Given I own playlist 10 and song 1 is active
    When I PUT "/api/v1/favorites/1/" twice with CSRF
    Then there is one favorite relationship
    When I PUT "/api/v1/playlists/10/songs/1/" twice with CSRF
    Then the playlist contains song 1 once

  @TC-M-006
  Scenario: Retry an event
    Given song 1 has duration_ms 100000 and I am logged in
    When I POST the same PLAY event twice to "/api/v1/behaviors/"
    Then the first status is 201 and the second is 200
    And the event count is 1
    When I reuse its event_id with different position_ms
    Then the status is 409 with error_code "EVENT_CONFLICT"

  @TC-M-007
  Scenario: Seek cannot instantly count as completion
    Given a PLAY event for a 100000 millisecond song
    And server time advances 1000 milliseconds
    When I POST COMPLETE at position_ms 90000 to "/api/v1/behaviors/"
    Then the status is 409 with error_code "INVALID_TRANSITION"
    And no positive listening feedback is added

  @TC-M-008
  Scenario: Exact fusion oracle
    Given n is 10 and both routes have positive maximum scores
    And a song has normalized content 0.8 and collaborative score 0.5
    When I calculate a refresh for "/api/v1/recommendations/daily/refresh/"
    Then alpha_target is 0.6 and the song score is 0.68

  @TC-M-009
  Scenario: No collaborative neighbors
    Given my profile is nonzero and no collaborative neighbor is eligible
    When I GET "/api/v1/recommendations/daily/"
    Then alpha_effective is 1 and personalized source is "CONTENT"

  @TC-M-010
  Scenario: Empty library
    Given no songs satisfy eligibility
    When I GET "/api/v1/recommendations/daily/"
    Then the status is 200 with empty items
    And empty_reason is "NO_ELIGIBLE_SONGS"

  @TC-M-011
  Scenario: Honest popular fallback
    Given I have no content profile or collaborative contribution
    When I GET "/api/v1/recommendations/daily/"
    Then all items have source "HOT" and zero neighbors and no evidence tags
    And all explanations are "热门歌曲，供你探索"

  @TC-M-012
  Scenario: Reject fabricated temporal evidence
    Given an evaluation manifest has no real timestamps
    When I execute evaluate_recommender with seed 42
    Then the process exits 2 without claiming real temporal-split improvement
